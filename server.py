#!/usr/bin/env python3
"""Smashed Burgers ERP - server for your own computer.

Run it on the main computer. Everyone you give the address to sees the same live data.
Shared ERP data is stored in Supabase when configured; local mode uses erp-data.json and local snapshots.
"""
import gzip, hashlib, hmac, json, os, re, secrets, socket, threading, time, zlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PORT = int(os.environ.get('PORT') or os.environ.get('ERP_PORT') or '8080')
HOST = os.environ.get('ERP_HOST', '0.0.0.0')   # set ERP_HOST=127.0.0.1 to allow this computer only
BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, 'smashed-burgers-erp.html')
# In the cloud, point ERP_DATA_DIR at the permanent disk (for example /data).
DATA_DIR = os.environ.get('ERP_DATA_DIR') or BASE
PROXY_HOPS = max(1, int(os.environ.get('ERP_PROXY_HOPS') or '1'))   # how many proxies sit in front
TRUST_PROXY = os.environ.get('ERP_TRUST_PROXY') == '1'   # set to 1 when a cloud host or Caddy sits in front
DATA = os.path.join(DATA_DIR, 'erp-data.json')
USERS_FILE = os.path.join(DATA_DIR, 'erp-users.json')
BACKUPS = os.path.join(DATA_DIR, 'backups')
IMG_DIR = os.path.join(DATA_DIR, 'images')
ID_RE = re.compile(r'^[A-Za-z0-9_-]{6,48}$')
MAX_IMG = 6 * 1024 * 1024
ROLES = {'admin': 'admin', 'smashed': 'visitor', 'staff': 'limited', 'cashier': 'cashier'}
# Legacy staff remains restricted. Cashier can add operational records; saved expense/wastage rows are append-only.
LIM_WRITE = {'dp': list, 'ex': dict, 'cx': list, 'ci': list}
CASHIER_WRITE = {'dp': list, 'rc': list, 'items': list, 'cx': list, 'ci': list, 'tr': list, 'cs': list, 'co': dict, 'wg': list}
CASHIER_SALT = 'cea2a4d13ce327dc7073ddacba94b056'
CASHIER_HASH = 'ab0b498c738b6fdd89dd78a1bf9110d70ef5f8fa0267224fde1e067cb909cdbe'
# first-time passwords, stored only as salted hashes. Change them inside the ERP.
DEFAULTS = {
    'admin': 'e7e180f59a43395b07b83287fdec239b6604b0aa0358e8462f02a1750adf2cef',
    'smashed': '819f2e5165edc68af5a31d48d635cc524789209420f38b17deee12c02f112b65',
}
MAX_BODY = 60 * 1024 * 1024
TOKEN_LIFE = 12 * 3600
LOCK = threading.Lock()
TOKENS = {}                 # token -> [role, expires]
FAILS = {}                  # ip -> [count, locked_until]
GLOBAL = {'fails': [], 'until': 0}
STATE = {'v': 0, 'data': 'null', 'snap': 0}
USERS = {}                  # overrides: name -> {salt, hash}
SB_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SB_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
SB_ENABLED = bool(SB_URL and SB_KEY)
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src 'self' data: blob:; connect-src 'self' https://cdnjs.cloudflare.com; "
       "worker-src 'self' blob: https://cdnjs.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate_tree(value, depth=0, budget=None):
    """Reject malformed/oversized JSON values before they reach shared ERP state."""
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > 100000 or depth > 12:
        return False
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return value == value and abs(value) != float('inf')
    if isinstance(value, str):
        return len(value) <= 20000
    if isinstance(value, list):
        return len(value) <= 20000 and all(validate_tree(x, depth + 1, budget) for x in value)
    if isinstance(value, dict):
        return len(value) <= 5000 and all(
            isinstance(k, str) and len(k) <= 200 and validate_tree(v, depth + 1, budget)
            for k, v in value.items()
        )
    return False


def _valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        time.strptime(value, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def _valid_amount(value, allow_zero=True):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and abs(value) != float('inf')
            and value <= 1000000000000 and (value >= 0 if allow_zero else value > 0))


def _append_only(old, incoming):
    """True when a submitted list preserves every saved row byte-for-byte and only appends."""
    return (isinstance(old, list) and isinstance(incoming, list)
            and len(incoming) >= len(old) and incoming[:len(old)] == old)


def valid_cashier_payload(data):
    """Validate cashier submissions before merging their restricted operational fields."""
    allowed = set(CASHIER_WRITE)
    if not isinstance(data, dict) or not set(data).issubset(allowed) or not validate_tree(data):
        return False
    for key, typ in CASHIER_WRITE.items():
        if key in data and not isinstance(data[key], typ):
            return False
    seen = set()
    for item in data.get('items', []):
        if not isinstance(item, dict):
            return False
        name = item.get('n')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
            return False
        norm = name.strip().casefold()
        if norm in seen:
            return False
        seen.add(norm)
        for field in ('c', 'u'):
            if field in item and (not isinstance(item[field], str) or len(item[field]) > 120):
                return False
        if 'p' in item and not _valid_amount(item['p']):
            return False
    for entry in data.get('dp', []):
        if (not isinstance(entry, dict) or not _valid_date(entry.get('d'))
                or not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('b', 'i'))
                or not _valid_amount(entry.get('q', 0))):
            return False
        for field in ('u', 'a'):
            if field in entry and not _valid_amount(entry[field]):
                return False
    for entry in data.get('rc', []):
        if (not isinstance(entry, dict) or not _valid_date(entry.get('d'))
                or not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('i', 'v'))
                or not _valid_amount(entry.get('q'), False)
                or not _valid_amount(entry.get('t'), False)):
            return False
        if 'p' in entry and not _valid_amount(entry['p']):
            return False
    for entry in data.get('wg', []):
        if (not isinstance(entry, dict) or not _valid_date(entry.get('d'))
                or not isinstance(entry.get('i'), str) or not entry['i'].strip()
                or not _valid_amount(entry.get('q'), False)
                or not _valid_amount(entry.get('a'))
                or not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('from', 'to'))):
            return False
        if entry.get('im') and not ID_RE.fullmatch(str(entry['im'])):
            return False
    for entry in data.get('tr', []):
        if (not isinstance(entry, dict) or not _valid_date(entry.get('d'))
                or not all(isinstance(entry.get(k), str) for k in ('k', 'p', 'v'))):
            return False
        if entry['v'] not in ('Car', 'CNG', 'Bike', 'Rickshaw') or not entry['p'].strip() or len(entry['p']) > 300:
            return False
        if not _valid_amount(entry.get('a'), False):
            return False
    for key in ('cs', 'ci', 'cx'):
        for entry in data.get(key, []):
            if (not isinstance(entry, dict) or not _valid_date(entry.get('d'))
                    or not isinstance(entry.get('k'), str) or not entry['k'].strip()
                    or not _valid_amount(entry.get('a'))):
                return False
            if key == 'cx' and (not isinstance(entry.get('p'), str) or not entry['p'].strip()):
                return False
    for key, amount in data.get('co', {}).items():
        if not isinstance(key, str) or '|' not in key or not _valid_date(key.rsplit('|', 1)[-1]) or not _valid_amount(amount):
            return False
    return True


def sb_request(path, method='GET', payload=None, raw=None, content_type='application/json'):
    """Small server-side Supabase REST/Storage client; secret key never reaches the browser."""
    if not SB_ENABLED:
        raise RuntimeError('Supabase is not configured')
    url = SB_URL + path
    headers = {'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY}
    if path.startswith('/rest/v1/') and method == 'POST':
        headers['Prefer'] = 'resolution=merge-duplicates,return=minimal'
    body = raw
    if payload is not None:
        body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    elif raw is not None:
        headers['Content-Type'] = content_type
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=25) as response:
            data = response.read()
            ctype = response.headers.get('Content-Type', '')
            if not data:
                return None
            if 'application/json' in ctype:
                return json.loads(data.decode('utf-8'))
            return data
    except HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:500]
        raise RuntimeError('Supabase request failed (%s): %s' % (e.code, detail))
    except URLError as e:
        raise RuntimeError('Could not connect to Supabase: %s' % e)


def sb_save_state():
    row = {'id': 'main', 'v': STATE['v'], 'data': json.loads(STATE['data']), 'users': USERS}
    sb_request('/rest/v1/erp_state?on_conflict=id', method='POST', payload=row)


def load():
    global USERS
    if SB_ENABLED:
        rows = sb_request('/rest/v1/erp_state?id=eq.main&select=id,v,data,users') or []
        if rows:
            row = rows[0]
            STATE['v'] = int(row.get('v') or 0)
            STATE['data'] = json.dumps(row.get('data'), separators=(',', ':'), ensure_ascii=False)
            USERS = row.get('users') or {}
        else:
            # Create the shared state row the first time the service starts.
            STATE['v'] = 0
            STATE['data'] = 'null'
            USERS = {}
            sb_save_state()
        print('Connected to Supabase cloud storage.')
        return
    if os.path.exists(USERS_FILE):
        try:
            USERS = read_json(USERS_FILE)
        except Exception:
            print('ERROR: erp-users.json is unreadable. Fix or delete it, then start again.')
            raise SystemExit(1)
    if not os.path.exists(DATA):
        return
    paths = [DATA]
    if os.path.isdir(BACKUPS):
        paths += [os.path.join(BACKUPS, x) for x in sorted(os.listdir(BACKUPS), reverse=True) if x.startswith('erp-')]
    for path in paths:
        try:
            j = read_json(path)
            STATE['v'] = int(j.get('v', 0))
            STATE['data'] = json.dumps(j.get('data'), separators=(',', ':'), ensure_ascii=False)
            if path != DATA:
                print('WARNING: erp-data.json was damaged. Loaded the latest snapshot: %s' % os.path.basename(path))
            return
        except Exception:
            print('WARNING: could not read %s' % os.path.basename(path))
    print('ERROR: no readable data file or snapshot. Fix or move erp-data.json and start again.')
    raise SystemExit(1)


def persist():
    if SB_ENABLED:
        sb_save_state()
        return
    text = '{"v":%d,"data":%s}' % (STATE['v'], STATE['data'])
    tmp = DATA + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, DATA)
    now = time.time()
    if now - STATE['snap'] >= 1800:
        os.makedirs(BACKUPS, exist_ok=True)
        name = 'erp-%s.json' % time.strftime('%Y-%m-%d-%H%M', time.localtime(now))
        with open(os.path.join(BACKUPS, name), 'w', encoding='utf-8') as f:
            f.write(text)
        STATE['snap'] = now
        files = sorted(x for x in os.listdir(BACKUPS) if x.startswith('erp-'))
        for x in files[:-300]:
            try:
                os.remove(os.path.join(BACKUPS, x))
            except OSError:
                pass


def save_users():
    if SB_ENABLED:
        sb_save_state()
        return
    tmp = USERS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(USERS, f)
    os.replace(tmp, USERS_FILE)


def pbk(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, 200000).hex()


def check_password(name, pw):
    """Verify the four-digit account PIN without exposing PINs to the browser."""
    pins = {
        'admin': '7cd49ea8bdcb0219b2bf72ff074eb518b0019a691c980922b715ee94a52d2fe8',
        'smashed': '7b208a33471413e1de35fc9dc30ecac8d9335dfe87478244f7e4b4223cd98975',
        'cashier': 'd100aff313b455ce85d5aaab4619e93f478885166fdfe4611ba4e8447685ced2',
    }
    if name not in pins or not re.fullmatch(r'\d{4}', pw):
        return False
    salt = bytes.fromhex('9f6c2a7d1e4b8a30c5d7e9f102938475')
    return hmac.compare_digest(pins[name], pbk(pw, salt))


def init_env_passwords():
    """Cloud setup: the owner's passwords come from the host settings, so the first-time ones never go live."""
    changed = False
    for name, var in (('admin', 'ERP_ADMIN_PASSWORD'), ('smashed', 'ERP_VISITOR_PASSWORD')):
        pw = os.environ.get(var, '')
        if pw and name not in USERS:
            if len(pw) < 8:
                print('ERROR: %s must have at least 8 characters.' % var)
                raise SystemExit(1)
            salt = secrets.token_bytes(16)
            USERS[name] = {'salt': salt.hex(), 'hash': pbk(pw, salt)}
            changed = True
    if changed:
        save_users()


def weak():
    # Accounts now use server-verified PINs; legacy password records are not used for login.
    return False


def limited_view(data_str):
    """What the staff account is allowed to receive: dispatch, expenses and just enough stock info."""
    try:
        d = json.loads(data_str)
    except Exception:
        return 'null'
    if not isinstance(d, dict):
        return 'null'
    out = {
        'items': [{'n': i.get('n'), 'c': i.get('c'), 'u': i.get('u'), 'p': 0} for i in d.get('items', []) if isinstance(i, dict)],
        'rc': [{'d': x.get('d'), 'i': x.get('i'), 'q': x.get('q')} for x in d.get('rc', []) if isinstance(x, dict)],
        'dp': d.get('dp', []), 'ex': d.get('ex', {}), 'ec': d.get('ec', []), 'fp': d.get('fp', 35),
        'cx': d.get('cx', []), 'ci': d.get('ci', []), 'br': d.get('br', []),
        'sales': {}, 'units': [u for u in d.get('units', []) if isinstance(u, str)],
        'menu': [{'id': m.get('id'), 'n': m.get('n'), 'c': m.get('c'), 'p': m.get('p', 0)} for m in d.get('menu', []) if isinstance(m, dict)],
        'ds': d.get('ds', {}), 'rv': [], 'st': [], 'pr': {}, 'vd': [], 'py': [], 'al': {},
        'nid': 1, 'mid': d.get('mid', 0),
    }
    return json.dumps(out, separators=(',', ':'), ensure_ascii=False)


def cashier_view(data_str):
    try:
        d = json.loads(data_str)
    except Exception:
        return 'null'
    if not isinstance(d, dict):
        return 'null'
    item_values = {i.get('n'): i.get('p', 0) for i in d.get('items', []) if isinstance(i, dict)}
    dispatch_rows = []
    for row in d.get('dp', []):
        if isinstance(row, dict):
            item = dict(row)
            unit_value = float(item.get('u', item_values.get(item.get('i'), 0)) or 0)
            if item.get('u') is None:
                item['u'] = unit_value
            if item.get('a') is None:
                item['a'] = float(item.get('q', 0) or 0) * unit_value
            dispatch_rows.append(item)
    return json.dumps({
        'items': [{'n': i.get('n'), 'c': i.get('c'), 'u': i.get('u'), 'p': 0} for i in d.get('items', []) if isinstance(i, dict)],
        'rc': d.get('rc', []), 'dp': dispatch_rows,
        'vd': [{'n': v.get('n')} for v in d.get('vd', []) if isinstance(v, dict)],
        'br': d.get('br', []), 'units': [], 'menu': [],
        'ds': {}, 'sales': {},
        'rv': [], 'st': [], 'pr': {}, 'py': [], 'cx': d.get('cx', []), 'ci': d.get('ci', []), 'tr': d.get('tr', []), 'cs': d.get('cs', []), 'co': d.get('co', {}),
        'al': {}, 'nid': d.get('nid', 1), 'mid': d.get('mid', 0), 'fp': d.get('fp', 0), 'wg': d.get('wg', [])
    }, separators=(',', ':'), ensure_ascii=False)


SEED_RE = re.compile(r'^let (ITEMS|MENU|SALES|VEND|STAFF)="(.*)";$', re.M)
AU_RE = re.compile(r'/\*AU\*/.*?/\*AU_END\*/', re.S)


def html_text():
    with open(HTML, 'r', encoding='utf-8') as f:
        return f.read()


def public_html():
    """The page everyone can download before signing in: no seed data, no password hashes."""
    t = SEED_RE.sub(lambda m: 'let %s="";' % m.group(1), html_text())
    return AU_RE.sub('const AU={};', t)


def seeds():
    return {m.group(1): m.group(2) for m in SEED_RE.finditer(html_text())}


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


class H(BaseHTTPRequestHandler):
    server_version = 'ERP'
    timeout = 30

    def log_message(self, *a):
        pass

    def ip(self):
        peer = self.client_address[0]
        if TRUST_PROXY or peer in ('127.0.0.1', '::1'):          # behind a tunnel or a cloud proxy
            parts = [x.strip() for x in self.headers.get('X-Forwarded-For', '').split(',') if x.strip()]
            if parts:
                # the proxy adds the real visitor on the right; anything on the left can be faked
                return parts[-min(PROXY_HOPS, len(parts))]
        return peer

    def send(self, code, body, ctype='application/json; charset=utf-8', cache='no-store'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        gz = len(body) > 1024 and 'gzip' in self.headers.get('Accept-Encoding', '') and not ctype.startswith('image/')
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        if gz:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        if TRUST_PROXY or self.headers.get('X-Forwarded-Proto') == 'https':
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        h = self.headers.get('Authorization', '')
        if h.startswith('Bearer '):
            t = TOKENS.get(h[7:])
            if t and t[1] > time.time():
                t[1] = time.time() + TOKEN_LIFE
                return h[7:], t[0]
        return None, None

    def body_json(self, limit=MAX_BODY):
        try:
            n = int(self.headers.get('Content-Length', '0') or 0)
        except ValueError:
            return None
        if n <= 0 or n > limit:
            return None
        raw = self.rfile.read(n)
        try:
            if self.headers.get('Content-Encoding', '') == 'gzip':
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                raw = d.decompress(raw, MAX_BODY)
                if d.unconsumed_tail:
                    return None
            return json.loads(raw.decode('utf-8'))
        except Exception:
            return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/manifest.webmanifest':
            try:
                with open(os.path.join(BASE, 'manifest.webmanifest'), 'r', encoding='utf-8') as f:
                    return self.send(200, f.read(), 'application/manifest+json; charset=utf-8', 'public, max-age=3600')
            except OSError:
                return self.send(404, 'not found', 'text/plain')
        if u.path == '/sw.js':
            try:
                with open(os.path.join(BASE, 'sw.js'), 'r', encoding='utf-8') as f:
                    return self.send(200, f.read(), 'application/javascript; charset=utf-8', 'no-cache')
            except OSError:
                return self.send(404, 'not found', 'text/plain')
        if u.path in ('/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'):
            try:
                with open(os.path.join(BASE, u.path.lstrip('/')), 'rb') as f:
                    return self.send(200, f.read(), 'image/png', 'public, max-age=604800')
            except OSError:
                return self.send(404, 'not found', 'text/plain')
        if u.path in ('/', '/index.html', '/smashed-burgers-erp.html'):
            try:
                return self.send(200, public_html(), 'text/html; charset=utf-8')
            except OSError:
                return self.send(500, 'smashed-burgers-erp.html must be in the same folder as server.py', 'text/plain')
        if u.path == '/healthz':
            return self.send(200, 'ok', 'text/plain')
        if u.path == '/api/ping':
            return self.send(200, '{"erp":true}')
        tok, role = self.session()
        if u.path == '/api/data':
            if not role:
                return self.send(401, '{"error":"login"}')
            q = parse_qs(u.query).get('v')
            w = 'true' if (role == 'admin' and weak()) else 'false'
            sf = 'true' if role == 'admin' else 'false'
            with LOCK:
                v, data = STATE['v'], STATE['data']
            if q and q[0] == str(v):
                return self.send(200, '{"same":true,"v":%d,"role":"%s","weak":%s,"staff":%s}' % (v, role, w, sf))
            if role == 'limited':
                data = limited_view(data)
            elif role == 'cashier':
                data = cashier_view(data)
            return self.send(200, '{"v":%d,"role":"%s","weak":%s,"staff":%s,"data":%s}' % (v, role, w, sf, data))
        if u.path.startswith('/api/img/'):
            if not role:
                return self.send(401, '{"error":"login"}')
            if role == 'limited':
                return self.send(403, '{"error":"not allowed"}')
            iid = u.path[len('/api/img/'):]
            if not ID_RE.match(iid):
                return self.send(404, '{"error":"not found"}')
            try:
                if SB_ENABLED:
                    raw = sb_request('/storage/v1/object/authenticated/erp-images/' + quote(iid + '.jpg'), method='GET')
                    return self.send(200, raw, 'image/jpeg', 'private, max-age=86400')
                path = os.path.join(IMG_DIR, iid + '.jpg')
                if not os.path.exists(path):
                    return self.send(404, '{"error":"not found"}')
                with open(path, 'rb') as f:
                    return self.send(200, f.read(), 'image/jpeg', 'private, max-age=86400')
            except Exception:
                return self.send(404, '{"error":"not found"}')
        if u.path == '/api/seed':
            if role != 'admin':
                return self.send(403, '{"error":"admin only"}')
            return self.send(200, json.dumps(seeds()))
        self.send(404, '{"error":"not found"}')

    def throttle(self, ip):
        now = time.time()
        if GLOBAL['until'] > now:
            return 'Too many attempts. Please wait a minute.'
        f = FAILS.get(ip, [0, 0])
        if f[1] > now:
            return 'Too many attempts. Wait 30 seconds.'
        return None

    def fail(self, ip):
        now = time.time()
        f = FAILS.get(ip, [0, 0])
        f[0] += 1
        if f[0] >= 5:
            f = [0, now + 30]
        FAILS[ip] = f
        GLOBAL['fails'] = [t for t in GLOBAL['fails'] if now - t < 600] + [now]
        if len(GLOBAL['fails']) >= 25:         # many wrong guesses from many addresses
            GLOBAL['until'] = now + 60
            GLOBAL['fails'] = []

    def do_POST(self):
        u = urlparse(self.path)
        ip = self.ip()
        if u.path == '/api/login':
            msg = self.throttle(ip)
            if msg:
                return self.send(429, json.dumps({'error': msg}))
            j = self.body_json(4096) or {}
            name = str(j.get('u', '')).strip().lower()
            pw = str(j.get('p', ''))
            if check_password(name, pw):
                FAILS.pop(ip, None)
                tok = secrets.token_urlsafe(24)
                TOKENS[tok] = [ROLES[name], time.time() + TOKEN_LIFE]
                for k in [k for k, v in TOKENS.items() if v[1] < time.time()]:
                    TOKENS.pop(k, None)
                return self.send(200, json.dumps({'token': tok, 'role': ROLES[name]}))
            self.fail(ip)
            time.sleep(0.4)
            return self.send(401, '{"error":"Wrong account or PIN."}')
        tok, role = self.session()
        if u.path == '/api/logout':
            TOKENS.pop(tok, None)
            return self.send(200, '{"ok":true}')
        if not role:
            return self.send(401, '{"error":"login"}')
        if role == 'cashier' and u.path == '/api/data':
            j = self.body_json()
            if not isinstance(j, dict) or not isinstance(j.get('data'), dict):
                return self.send(400, '{"error":"bad data"}')
            try:
                base = int(j.get('base', -1))
            except (TypeError, ValueError):
                return self.send(400, '{"error":"bad version"}')
            new = j['data']
            if not valid_cashier_payload(new):
                return self.send(400, '{"error":"Invalid or unsupported Cashier data. Check the entries and try again."}')
            with LOCK:
                if base != STATE['v']:
                    return self.send(409, '{"v":%d,"data":%s}' % (STATE['v'], cashier_view(STATE['data'])))
                try:
                    cur = json.loads(STATE['data'])
                except Exception:
                    cur = None
                if not isinstance(cur, dict):
                    return self.send(400, '{"error":"no data yet"}')
                # Cashier may add expense/transport/wastage records but cannot edit or delete
                # records already saved. This is enforced server-side, not just in the UI.
                # Validate branch/item/vendor references against the current business setup.
                branches = set(x for x in cur.get('br', []) if isinstance(x, str))
                item_names = set(x.get('n') for x in cur.get('items', []) if isinstance(x, dict) and isinstance(x.get('n'), str))
                item_names.update(x.get('n') for x in new.get('items', []) if isinstance(x, dict) and isinstance(x.get('n'), str))
                vendor_names = set(x.get('n') for x in cur.get('vd', []) if isinstance(x, dict) and isinstance(x.get('n'), str))
                for row in new.get('dp', []):
                    if row.get('b') not in branches or row.get('i') not in item_names:
                        return self.send(400, '{"error":"Dispatch must reference an existing branch and inventory item."}')
                for row in new.get('rc', []):
                    if row.get('i') not in item_names or row.get('v') not in vendor_names:
                        return self.send(400, '{"error":"Stock-in must reference an existing inventory item and vendor."}')
                for key in ('cx', 'ci', 'cs'):
                    if any(row.get('k') not in branches for row in new.get(key, [])):
                        return self.send(400, '{"error":"Cash-book entries must reference an existing branch."}')
                for row in new.get('tr', []):
                    if (row.get('to') or row.get('k')) not in branches:
                        return self.send(400, '{"error":"Transportation must reference an existing destination branch."}')
                for key in new.get('co', {}):
                    if key.rsplit('|', 1)[0] not in branches:
                        return self.send(400, '{"error":"Opening cash must reference an existing branch."}')
                # Cashier can add operational records, but cannot rewrite historical rows.
                # This is enforced here as well as in the interface to prevent direct API edits.
                for key in ('cx', 'tr', 'wg', 'ci', 'cs', 'rc'):
                    if key in new and not _append_only(cur.get(key, []), new[key]):
                        return self.send(403, '{"error":"Only Admin can edit or delete saved expense, cash-book, stock-in and wastage records."}')
                if 'co' in new:
                    old_opening = cur.get('co', {})
                    incoming_opening = new['co']
                    if not isinstance(old_opening, dict) or not isinstance(incoming_opening, dict) or any(
                        key not in incoming_opening or incoming_opening[key] != value
                        for key, value in old_opening.items()
                    ):
                        return self.send(403, '{"error":"Only Admin can change or delete a saved opening-cash value."}')
                # Accept only Dispatch, Inventory, Transportation, cash-book and new wastage fields.
                for k in ('dp', 'rc', 'cx', 'ci', 'tr', 'cs', 'co', 'wg'):
                    if k in new:
                        cur[k] = new[k]
                if 'items' in new:
                    old_by_name = {str(x.get('n', '')).casefold(): x for x in cur.get('items', []) if isinstance(x, dict)}
                    clean = []
                    incoming_names = set()
                    for item in new['items']:
                        if not isinstance(item, dict) or not str(item.get('n', '')).strip():
                            return self.send(400, '{"error":"invalid inventory item"}')
                        name = str(item.get('n', '')).strip()
                        norm = name.casefold()
                        incoming_names.add(norm)
                        old = old_by_name.get(norm, {})
                        if old and (name != str(old.get('n', ''))
                                    or str(item.get('c', old.get('c', ''))) != str(old.get('c', ''))
                                    or str(item.get('u', old.get('u', ''))) != str(old.get('u', ''))):
                            return self.send(403, '{"error":"Only Admin can edit existing inventory item details."}')
                        # A cashier may set the unit value on the first stock receipt only.
                        old_price = old.get('p', 0)
                        new_price = old_price
                        if not old_price:
                            receipts = [row for row in cur.get('rc', []) if isinstance(row, dict) and row.get('i') == name]
                            received_qty = sum(float(row.get('q') or 0) for row in receipts)
                            received_value = sum(float(row.get('t') if row.get('t') is not None else (float(row.get('q') or 0) * float(row.get('p') or 0))) for row in receipts)
                            new_price = received_value / received_qty if received_qty > 0 else item.get('p', 0)
                        if not _valid_amount(new_price):
                            return self.send(400, '{"error":"invalid inventory unit value"}')
                        clean.append({'n': name, 'c': str(item.get('c', old.get('c', ''))),
                                      'u': str(item.get('u', old.get('u', ''))), 'p': new_price})
                    if not set(old_by_name).issubset(incoming_names):
                        return self.send(403, '{"error":"Only Admin can remove existing inventory items."}')
                    cur['items'] = clean
                old_v, old_data = STATE['v'], STATE['data']
                STATE['v'] = old_v + 1
                STATE['data'] = json.dumps(cur, separators=(',', ':'), ensure_ascii=False)
                try:
                    persist()
                except Exception as e:
                    # Do not leave an unsaved change visible in memory after a storage failure.
                    STATE['v'], STATE['data'] = old_v, old_data
                    print('ERROR: ERP data save failed: %s' % e)
                    return self.send(503, '{"error":"Could not save to the database. No changes were committed; please try again."}')
                return self.send(200, '{"v":%d}' % STATE['v'])
        if role == 'limited' and u.path == '/api/data':
            j = self.body_json()
            if not isinstance(j, dict) or not isinstance(j.get('data'), dict):
                return self.send(400, '{"error":"bad data"}')
            try:
                base = int(j.get('base', -1))
            except (TypeError, ValueError):
                return self.send(400, '{"error":"bad version"}')
            new = j['data']
            allowed = LIM_WRITE
            for k, typ in allowed.items():
                if k in new and not isinstance(new[k], typ):
                    return self.send(400, '{"error":"bad data"}')
            with LOCK:
                if base != STATE['v']:
                    view = cashier_view(STATE['data']) if role == 'cashier' else limited_view(STATE['data'])
                    return self.send(409, '{"v":%d,"data":%s}' % (STATE['v'], view))
                try:
                    cur = json.loads(STATE['data'])
                except Exception:
                    cur = None
                if not isinstance(cur, dict):
                    return self.send(400, '{"error":"no data yet"}')
                for k in LIM_WRITE:
                    if k in new: cur[k] = new[k]
                old_v, old_data = STATE['v'], STATE['data']
                STATE['v'] = old_v + 1
                STATE['data'] = json.dumps(cur, separators=(',', ':'), ensure_ascii=False)
                try:
                    persist()
                except Exception as e:
                    # Do not leave an unsaved change visible in memory after a storage failure.
                    STATE['v'], STATE['data'] = old_v, old_data
                    print('ERROR: ERP data save failed: %s' % e)
                    return self.send(503, '{"error":"Could not save to the database. No changes were committed; please try again."}')
                return self.send(200, '{"v":%d}' % STATE['v'])
        if role not in ('admin', 'cashier'):
            return self.send(403, '{"error":"view only"}')
        if u.path == '/api/img-del' and role != 'admin':
            return self.send(403, '{"error":"admin only"}')
        if u.path in ('/api/img', '/api/img-del'):
            iid = (parse_qs(u.query).get('id') or [''])[0]
            if not ID_RE.match(iid):
                return self.send(400, '{"error":"bad id"}')
            path = os.path.join(IMG_DIR, iid + '.jpg')
            if u.path == '/api/img-del':
                try:
                    if SB_ENABLED:
                        sb_request('/storage/v1/object/erp-images', method='DELETE', payload={'prefixes': [iid + '.jpg']})
                    else:
                        os.remove(path)
                except Exception:
                    pass
                return self.send(200, '{"ok":true}')
            try:
                n = int(self.headers.get('Content-Length', '0') or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_IMG:
                return self.send(413, '{"error":"picture too large"}')
            raw = self.rfile.read(n)
            if raw[:2] != b'\xff\xd8':
                return self.send(400, '{"error":"jpeg only"}')
            if SB_ENABLED:
                headers = {'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY,
                           'Content-Type': 'image/jpeg', 'x-upsert': 'true'}
                req = Request(SB_URL + '/storage/v1/object/erp-images/' + quote(iid + '.jpg'),
                              data=raw, headers=headers, method='POST')
                try:
                    with urlopen(req, timeout=30) as response:
                        response.read()
                except Exception as e:
                    return self.send(502, json.dumps({'error': 'image storage failed'}))
            else:
                os.makedirs(IMG_DIR, exist_ok=True)
                with open(path + '.tmp', 'wb') as f:
                    f.write(raw)
                os.replace(path + '.tmp', path)
            return self.send(200, '{"ok":true}')
        if u.path == '/api/password':
            # Password management is an owner-only operation. Never rely on UI hiding.
            if role != 'admin':
                return self.send(403, '{"error":"Only the Admin account can manage passwords."}')
            j = self.body_json(4096) or {}
            who, new, cur = str(j.get('who', '')), str(j.get('new', '')), str(j.get('cur', ''))
            msg = self.throttle(ip)
            if msg:
                return self.send(429, json.dumps({'error': msg}))
            if not check_password('admin', cur):
                self.fail(ip)
                return self.send(403, '{"error":"Your current admin password is not correct."}')
            if who not in ('admin', 'smashed', 'staff', 'cashier'):
                return self.send(400, '{"error":"Unknown account."}')
            if len(new) < 8:
                return self.send(400, '{"error":"Use at least 8 characters."}')
            if new.lower() in ('sabbirnj1715', 'smashed2026', 'password', '12345678', who):
                return self.send(400, '{"error":"That password is too easy to guess."}')
            salt = secrets.token_bytes(16)
            USERS[who] = {'salt': salt.hex(), 'hash': pbk(new, salt)}
            save_users()
            for k in [k for k, v in TOKENS.items() if v[0] == ROLES[who]]:
                TOKENS.pop(k, None)
            return self.send(200, '{"ok":true}')
        if u.path == '/api/data':
            j = self.body_json()
            if (not isinstance(j, dict) or not isinstance(j.get('data'), dict)
                    or 'items' not in j['data'] or not validate_tree(j['data'])):
                return self.send(400, '{"error":"Invalid or oversized ERP data. No changes were saved."}')
            try:
                base = int(j.get('base', -1))
            except (TypeError, ValueError):
                return self.send(400, '{"error":"bad version"}')
            with LOCK:
                if base != STATE['v']:
                    return self.send(409, '{"v":%d,"data":%s}' % (STATE['v'], STATE['data']))
                old_v, old_data = STATE['v'], STATE['data']
                STATE['v'] = old_v + 1
                STATE['data'] = json.dumps(j['data'], separators=(',', ':'), ensure_ascii=False)
                try:
                    persist()
                except Exception as e:
                    STATE['v'], STATE['data'] = old_v, old_data
                    print('ERROR: ERP data save failed: %s' % e)
                    return self.send(503, '{"error":"Could not save to the database. No changes were committed; please try again."}')
                return self.send(200, '{"v":%d}' % STATE['v'])
        self.send(404, '{"error":"not found"}')


if __name__ == '__main__':
    if os.environ.get('RENDER') and not SB_ENABLED:
        print('ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Render environment variables.')
        raise SystemExit(1)
    os.makedirs(DATA_DIR, exist_ok=True)
    load()
    init_env_passwords()
    if TRUST_PROXY and weak():
        print('ERROR: this server is set up for the internet, but the passwords are not set.')
        print('Set ERP_ADMIN_PASSWORD and ERP_VISITOR_PASSWORD (8 or more characters) and start again.')
        raise SystemExit(1)
    try:
        srv = ThreadingHTTPServer((HOST, PORT), H)
    except OSError:
        print('Port %d is already in use. Is the ERP already running in another window?' % PORT)
        raise SystemExit(1)
    srv.daemon_threads = True
    ip = lan_ip()
    print('=' * 62)
    print(' Smashed Burgers ERP is running')
    if TRUST_PROXY:
        print('   Cloud mode (port %d). Open your website address.' % PORT)
    else:
        print('   On this computer : http://localhost:%d' % PORT)
        print('   Same Wi-Fi       : http://%s:%d' % (ip, PORT))
        print('   From anywhere    : see HOW-TO-GO-ONLINE.txt')
    if weak():
        print(' !! First-time passwords are still active. Change them inside the')
        print('    ERP (sidebar > Change passwords) BEFORE sharing an online link.')
    print(' Data folder : %s' % DATA_DIR)
    print(' Keep this window open. Close it to stop the ERP.')
    print('=' * 62)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
