const CACHE_NAME = 'archivex-pwa-v9';
const DOCS_CACHE_NAME = 'archivex-docs-v2';

const STATIC_ASSETS = [
    '/',
    '/manifest.json',
    '/static/manifest.json',
    '/static/css/style.css',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/static/icons/icon-192.png?v=3',
    '/static/icons/icon-512.png?v=3',
    '/icons/icon-192.png?v=3',
    '/icons/icon-512.png?v=3',
    '/static/js/install-pwa.js',
    '/static/js/archivex-spa.js',
    '/static/vendor/pdfjs/pdf.min.js',
    '/static/vendor/pdfjs/pdf.worker.min.js'
];

// Installation : Prise en charge immédiate
self.addEventListener('install', (event) => {
    console.log('[Service Worker v9] Installation PWA ArchivEx...');
    event.waitUntil(
        caches.open(CACHE_NAME).then(async (cache) => {
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

// Activation : Nettoyage immédiat de TOUS les anciens caches (en préservant archivex-docs-v2)
self.addEventListener('activate', (event) => {
    console.log('[Service Worker v8] Activation & purge anciens caches...');
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(
                keyList.map((key) => {
                    if (key !== CACHE_NAME && key !== DOCS_CACHE_NAME) {
                        console.log('[Service Worker] Suppression ancien cache obsolète:', key);
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch : Stratégie optimisée avec support complet de la lecture hors-ligne
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);

    // 1. NE JAMAIS INTERCEPTER : Administration et paiements sensibles (gérés exclusivement en ligne)
    // NOTE : Le flux binaire /stream-watermarked/ est géré directement par viewer.html via la Storage API (archivex-docs-v2).
    // Les pages HTML /viewer/ DOIVENT être interceptées pour s'ouvrir hors-ligne !
    if (
        url.pathname.includes('/stream-watermarked/') ||
        url.pathname.startsWith('/django-admin/') ||
        url.pathname.startsWith('/administration/') ||
        url.pathname.startsWith('/payments/process/') ||
        url.pathname.startsWith('/payments/webhook/') ||
        url.pathname.startsWith('/accounts/api/log-click/')
    ) {
        return; // Le navigateur traite la requête en direct
    }

    // 2. RESSOURCES STATIQUES ET LIBRAIRIE PDF.JS : Cache d'abord, secours réseau
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

    // 3. NAVIGATION (PAGES DU SITE ET DU LECTEUR WEB) : Réseau en priorité, mise en cache, secours hors-ligne
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
                        // Fallback tolérant aux paramètres de requête (ex: ?type=exam)
                        return caches.match(event.request, { ignoreSearch: true }).then((matchWithoutSearch) => {
                            if (matchWithoutSearch) return matchWithoutSearch;
                            return caches.match('/').then((homeResponse) => {
                                return homeResponse || new Response(
                                    '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Hors-ligne — ArchivEx</title></head><body style="font-family:sans-serif;text-align:center;padding:50px;background:#071A49;color:#fff;"><h2>Vous êtes hors-ligne</h2><p>Ce contenu sera accessible dès que vous l\'aurez consulté une première fois avec une connexion Internet.</p><button onclick="window.location.reload()" style="padding:10px 20px;border-radius:10px;background:#2563EB;color:#fff;border:none;cursor:pointer;">Réessayer</button></body></html>',
                                    { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                                );
                            });
                        });
                    });
                })
        );
        return;
    }

    // 4. AUTRES REQUÊTES GET
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
            .catch(() => caches.match(event.request))
    );
});