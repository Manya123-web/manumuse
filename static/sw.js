const CACHE = 'manumuse-v1';
const ASSETS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;
  
  // Don't intercept API, stream, or external requests
  if (url.includes('/api/') || 
      url.includes('ytimg') || 
      url.includes('googlevideo') ||
      url.includes('proxy')) {
    return;
  }
  
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});