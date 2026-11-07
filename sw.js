const CACHE = 'smashed-erp-shell-v14';
const SHELL = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];
const NETWORK_TIMEOUT_MS = 4000;

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache =>
      cache.addAll(SHELL.map(u => new Request(u, { cache: 'reload' })))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  const isNav = req.mode === 'navigate';
  const isShell = SHELL.includes(url.pathname) || url.pathname === '/index.html';
  if (!isNav && !isShell) return;

  // Normalize the cache key: ignore query strings, treat /index.html and navigations as '/'
  const key = (isNav || url.pathname === '/index.html') ? '/' : url.pathname;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const network = fetch(req);

    // Update the cache in the background, kept alive via waitUntil
    event.waitUntil(
      network
        .then(res => (res.ok && !res.redirected) ? cache.put(key, res.clone()) : undefined)
        .catch(() => {})
    );

    try {
      return await Promise.race([
        network,
        new Promise((_, reject) => setTimeout(reject, NETWORK_TIMEOUT_MS)),
      ]);
    } catch {
      const hit = await cache.match(key);
      return hit || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
    }
  })());
});
