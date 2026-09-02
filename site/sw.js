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
 *     saves students' data).
 *
 * CACHE-FIRST HERE MEANS FOREVER. The audio branch below returns the cached
 * response without ever revalidating, and clip ids are POSITION-based
 * ({level}-w{week}-bc{i}), not content hashes — so re-rendering a clip
 * changes the bytes while the URL stays identical. A student who already
 * holds the old file will keep it for good.
 *
 * So: RE-RENDERING ANY SHIPPED CLIP REQUIRES BUMPING CACHE_NAME. It is the
 * only thing that evicts the old audio, because `activate` deletes every
 * cache whose key is not the current CACHE_NAME. Nothing enforces this
 * mechanically — the URL is unchanged, so no check can see the difference.
 * This comment used to claim these filenames "don't change content", which
 * is what made the v6 -> v7 bump easy to miss.
 */

// v8: broadcast clips peak-normalised + silence-trimmed (audio_postprocess.py).
//     The raw ONNX output shipped clips at inconsistent, often quiet levels
//     (peaks from -8.5 dBFS to near clipping on the same voice); the re-render
//     brings every clip to a consistent, full loudness. Without this bump a
//     student who had opened a page keeps the old quiet /audio/ clip for up to
//     a year, because sw caches .mp3 cache-first and Pages serves it immutable.
// v7: c1-w6-bc0 re-rendered af_nicole -> af_bella (152 -> 203 wpm). Without
//     this bump every student who had already opened that C1 week 6 page
//     would have kept the 152 wpm clip permanently, on the one descriptor
//     (C1.R.1) that is entirely a claim about delivery speed.
// v6: 189 broadcast clips re-voiced British -> American
const CACHE_NAME = 'empire-v8';
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
  // { cache: 'no-store' } bypasses the browser HTTP cache too, so a home-screen
  // PWA can never be pinned to a stale banner/CSS by an earlier max-age.
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
