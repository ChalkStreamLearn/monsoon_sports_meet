// ChalkStream — minimal offline shell cache.
//
// Caches the static page shell (HTML/CSS/JS/icons) so the site still opens
// when offline or on a flaky connection. Live data (scores, fixtures,
// standings, gallery) comes from Firestore's own onSnapshot listeners in
// js/app.js — those need a live connection and are NOT cached here; if
// there's no network, the page will open showing the last-rendered data
// from before it went offline, not brand-new data.
//
// Bump CACHE_NAME whenever you change which files are precached, so old
// clients don't get stuck serving a stale shell forever.
const CACHE_NAME = 'chalkstream-shell-v3';
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './js/app.js',
  './js/firebase.js',
  './favicon.ico',
  './favicon-96x96.png',
  './apple-touch-icon.png',
  './web-app-manifest-192x192.png',
  './web-app-manifest-512x512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    ).then(() => self.clients.claim())
  );
});

// HTML page navigations: network-first, so edits to index.html show up
// immediately on the next load instead of waiting for a CACHE_NAME bump.
// Falls back to the cached shell only if the network request fails
// (offline / flaky connection).
//
// Other same-origin static assets (css/js/icons): cache-first, since those
// rarely change and cache-first keeps the site feeling instant.
//
// Cross-origin requests (Firestore, Cloudinary, Google Fonts) always go
// straight to the network so live data is never served stale from here.
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  const isNavigation =
    event.request.mode === 'navigate' ||
    (event.request.method === 'GET' &&
      event.request.headers.get('accept')?.includes('text/html'));

  if (isNavigation) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      }).catch(() => cached);
    })
  );
});
