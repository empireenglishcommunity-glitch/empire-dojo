/**
 * Empire English Practice — Service Worker (Sahel S4)
 * Cache-first for static assets (HTML, CSS, JS, audio).
 */

const CACHE_NAME = 'empire-v1';
const OFFLINE_URL = '/offline.html';

// Pre-cache essential assets on install
const PRECACHE = [
  '/',
  '/css/empire.css',
  '/js/app.js',
  '/logo.png',
  '/favicon.png',
  '/offline.html',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET requests
  if (request.method !== 'GET') return;

  // Cache-first for static assets
  if (request.url.match(/\.(css|js|png|jpg|mp3|webm|json)$/) ||
      request.url.includes('/css/') ||
      request.url.includes('/js/') ||
      request.url.includes('/audio/')) {
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

  // Network-first for HTML pages, fallback to cache then offline page
  event.respondWith(
    fetch(request).then((response) => {
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
