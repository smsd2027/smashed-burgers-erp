#!/usr/bin/env python3
"""Smashed Burgers ERP - server for your own computer.

Run it on the main computer. Everyone you give the address to sees the same live data.
All data stays in erp-data.json next to this file. Snapshots are saved in "backups".
To reach it from anywhere, share it through a tunnel (see HOW-TO-GO-ONLINE.txt).
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
# Legacy staff remains restricted to Expenses/Dispatch. Cashier can use Inventory/Dispatch only.
LIM_WRITE = {'dp': list, 'ex': dict, 'cx': list, 'ci': list}
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
    if name not in ROLES:
        return False
    rec = USERS.get(name)
    if name == 'cashier' and not rec:
        return hmac.compare_digest(CASHIER_HASH, pbk(pw, bytes.fromhex(CASHIER_SALT)))
    if rec:
        return hmac.compare_digest(rec['hash'], pbk(pw, bytes.fromhex(rec['salt'])))
    if name not in DEFAULTS:      # the staff account only exists once the admin has created its password
        return False
    legacy = hashlib.sha256(('sb-erp|%s|%s' % (name, pw)).encode('utf-8')).hexdigest()
    return hmac.compare_digest(DEFAULTS[name], legacy)


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
    return any(n not in USERS for n in ('admin', 'smashed'))


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
        'sales': {}, 'units': [], 'menu': [], 'ds': {}, 'rv': [], 'st': [], 'pr': {}, 'vd': [], 'py': [], 'al': {},
        'nid': 1, 'mid': 0,
    }
    return json.dumps(out, separators=(',', ':'), ensure_ascii=False)


def cashier_view(data_str):
    try:
        d = json.loads(data_str)
    except Exception:
        return 'null'
    if not isinstance(d, dict):
        return 'null'
    return json.dumps({
        'items': [{'n': i.get('n'), 'c': i.get('c'), 'u': i.get('u'), 'p': 0} for i in d.get('items', []) if isinstance(i, dict)],
        'rc': d.get('rc', []), 'dp': d.get('dp', []),
        'vd': [{'n': v.get('n')} for v in d.get('vd', []) if isinstance(v, dict)],
        'br': d.get('br', []), 'units': [], 'menu': [], 'ds': {}, 'sales': {},
        'rv': [], 'st': [], 'pr': {}, 'py': [], 'ex': d.get('ex', {}), 'ec': d.get('ec', []), 'cx': d.get('cx', []), 'ci': d.get('ci', []),
        'al': {}, 'nid': d.get('nid', 1), 'mid': 0, 'fp': d.get('fp', 0)
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
        if u.path in ('/icon-192.png', '/icon-512.png'):
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
            if role in ('limited', 'cashier'):
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
            return self.send(401, '{"error":"Wrong ID or password."}')
        tok, role = self.session()
        if u.path == '/api/logout':
            TOKENS.pop(tok, None)
            return self.send(200, '{"ok":true}')
        if not role:
            return self.send(401, '{"error":"login"}')
        if role == 'cashier' and u.path == '/api/data':
            return self.send(403, '{"error":"Cashier has view-only access. Ask Admin to add or change records."}')
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
                STATE['v'] += 1
                STATE['data'] = json.dumps(cur, separators=(',', ':'), ensure_ascii=False)
                persist()
                return self.send(200, '{"v":%d}' % STATE['v'])
        if role != 'admin':
            return self.send(403, '{"error":"view only"}')
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
            if not isinstance(j, dict) or not isinstance(j.get('data'), dict) or 'items' not in j['data']:
                return self.send(400, '{"error":"bad data"}')
            try:
                base = int(j.get('base', -1))
            except (TypeError, ValueError):
                return self.send(400, '{"error":"bad version"}')
            with LOCK:
                if base != STATE['v']:
                    return self.send(409, '{"v":%d,"data":%s}' % (STATE['v'], STATE['data']))
                STATE['v'] += 1
                STATE['data'] = json.dumps(j['data'], separators=(',', ':'), ensure_ascii=False)
                persist()
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
