const CACHE_NAME = 'mcq-generator-v1';
const ASSETS_CACHE = 'assets-v1';

// Only cache static assets
const urlsToCache = [
  '/static/manifest.json',
  '/static/icons/icon_48x48.png',
  '/static/icons/icon_72x72.png',
  '/static/icons/icon_96x96.png',
  '/static/icons/icon_144x144.png',
  '/static/icons/icon_192x192.png',
  '/static/icons/icon_512x512.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js'
];

// Install event
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened cache');
        return cache.addAll(urlsToCache);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event
self.addEventListener('activate', event => {
  event.waitUntil(
    Promise.all([
      self.clients.claim(),
      // Clean up old caches
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames
            .filter(cacheName => cacheName !== CACHE_NAME && 
                               cacheName !== ASSETS_CACHE)
            .map(cacheName => caches.delete(cacheName))
        );
      })
    ])
  );
});

// Fetch event
self.addEventListener('fetch', event => {
  // Only cache static assets and CDN resources
  if (event.request.url.includes('/static/') || 
      event.request.url.startsWith('https://cdn.jsdelivr.net') ||
      event.request.url.startsWith('https://cdnjs.cloudflare.com')) {
    event.respondWith(
      caches.match(event.request)
        .then(response => {
          if (response) {
            return response;
          }
          return fetch(event.request).then(response => {
            // Check if we received a valid response
            if (!response || response.status !== 200 || response.type !== 'basic') {
              return response;
            }
            // Clone the response
            const responseToCache = response.clone();
            caches.open(ASSETS_CACHE)
              .then(cache => {
                cache.put(event.request, responseToCache);
              });
            return response;
          });
        })
    );
  }
}); 