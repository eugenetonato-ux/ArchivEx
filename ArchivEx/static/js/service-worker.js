const CACHE_NAME = 'archivex-v2';
const STATIC_ASSETS = [
    '/',
    '/manifest.json',
    '/static/manifest.json',
    '/static/css/style.css',
    '/static/images/logo.jpg',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/static/js/install-pwa.js'
];

// Installation : Mise en cache sécurisée ressource par ressource
self.addEventListener('install', (event) => {
    console.log('[Service Worker] Installation...');
    event.waitUntil(
        caches.open(CACHE_NAME).then(async (cache) => {
            console.log('[Service Worker] Pré-mise en cache des assets essentiels');
            for (const asset of STATIC_ASSETS) {
                try {
                    await cache.add(asset);
                } catch (err) {
                    console.warn('[Service Worker] Asset non mis en cache:', asset, err);
                }
            }
        }).then(() => self.skipWaiting())
    );
});

// Activation : Nettoyage des anciens caches et contrôle immédiat
self.addEventListener('activate', (event) => {
    console.log('[Service Worker] Activation...');
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(
                keyList.map((key) => {
                    if (key !== CACHE_NAME) {
                        console.log('[Service Worker] Suppression ancien cache:', key);
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch : Stratégie Réseau en priorité pour navigation, cache-first pour statiques
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);

    // Ne pas intercepter les requêtes Django admin ou authentification sensible
    if (url.pathname.startsWith('/django-admin/') || url.pathname.startsWith('/administration/')) {
        return;
    }

    // Ressources statiques et médias : Cache d'abord, secours réseau
    if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/icons/') || url.pathname.startsWith('/media/')) {
        event.respondWith(
            caches.match(event.request).then((cachedResponse) => {
                if (cachedResponse) return cachedResponse;
                return fetch(event.request).then((networkResponse) => {
                    if (networkResponse && networkResponse.status === 200) {
                        const responseClone = networkResponse.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    return networkResponse;
                }).catch(() => cachedResponse);
            })
        );
        return;
    }

    // Requêtes de navigation (pages HTML) : Réseau en priorité, secours sur cache
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request)
                .then((networkResponse) => {
                    if (networkResponse && networkResponse.status === 200) {
                        const responseClone = networkResponse.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    return networkResponse;
                })
                .catch(() => {
                    return caches.match(event.request).then((cachedResponse) => {
                        if (cachedResponse) return cachedResponse;
                        return caches.match('/').then((homeResponse) => {
                            return homeResponse || new Response(
                                '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Hors-ligne</title></head><body style="font-family:sans-serif;text-align:center;padding:50px;"><h2>Vous êtes hors-ligne</h2><p>Vérifiez votre connexion Internet pour charger de nouvelles pages.</p><button onclick="window.location.reload()">Réessayer</button></body></html>',
                                { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                            );
                        });
                    });
                })
        );
        return;
    }

    // Autres requêtes GET
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});