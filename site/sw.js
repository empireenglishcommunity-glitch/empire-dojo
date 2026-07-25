/**
 * Empire English Practice — Service Worker (Sahel S4 + Darb cache fix)
 *
 * Strategy:
 *   - CSS / JS / HTML / JSON  → NETWORK-FIRST (always get the latest, fall
 *     back to cache only when offline). This is critical: a cache-first
 *     policy on a fixed cache name meant returning students kept seeing a
 *     STALE empire.css forever (new JS rendered new calendar cells while
 *     the old CSS had no styles for them → unstyled purple links). Bug #2.
 *   - Images / audio (.png/.jpg/.mp3/.webm) → CACHE-FIRST (immutable, large;
 *     saves students' data). These filenames don't change content.
 *
 * The CACHE_NAME is versioned; bumping it purges every old cache on
 * activate, so this deploy also clears any stale empire-v1 assets.
 */

const CACHE_NAME = 'empire-v4';
const OFFLINE_URL = '/offline';

// Pre-cache only the offline fallback + icons (NOT css/js — those are
// network-first now, so precaching them stale would defeat the fix).
const PRECACHE = [
  '/offline',
  '/logo.png',
  '/favicon.png',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = request.url;

  // CACHE-FIRST only for big, immutable media (images + audio).
  if (url.match(/\.(png|jpg|jpeg|gif|webp|svg|mp3|webm|m4a|ogg)$/i) ||
      url.includes('/audio/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // NETWORK-FIRST for everything else (CSS, JS, HTML, JSON) — always fresh,
  // fall back to cache (then the offline page) only when the network fails.
  //
  // CRITICAL (PWA fix): use { cache: 'no-store' } so the fetch BYPASSES the
  // browser HTTP cache and truly hits the network. Plain fetch(request)
  // honors HTTP cache headers (e.g. max-age), so a long-cached file like
  // status.js was returned stale even under "network-first" — which is why
  // installed home-screen apps kept showing the OLD maintenance banner with
  // no way to hard-refresh. Bypassing the HTTP cache makes network-first
  // actually mean network-first; we still keep a copy in the SW cache for
  // true offline fallback.
  event.respondWith(
    fetch(request, { cache: 'no-store' }).then((response) => {
      if (response.ok) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
      }
      return response;
    }).catch(() =>
      caches.match(request).then((cached) => cached || caches.match(OFFLINE_URL))
    )
  );
});
