const CACHE_NAME = 'archivex-pwa-v3';
const DOCS_CACHE_NAME = 'archivex-docs-v1';

const STATIC_ASSETS = [
    '/',
    '/manifest.json',
    '/static/manifest.json',
    '/static/css/style.css',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/static/js/install-pwa.js',
    '/static/vendor/pdfjs/pdf.min.js',
    '/static/vendor/pdfjs/pdf.worker.min.js'
];

// Installation : Mise en cache sécurisée des assets essentiels et du moteur PDF.js
self.addEventListener('install', (event) => {
    console.log('[Service Worker] Installation PWA ArchivEx...');
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

// Activation : Nettoyage des anciens caches d'application sans effacer les documents hors-ligne
self.addEventListener('activate', (event) => {
    console.log('[Service Worker] Activation PWA...');
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(
                keyList.map((key) => {
                    if (key !== CACHE_NAME && key !== DOCS_CACHE_NAME) {
                        console.log('[Service Worker] Nettoyage ancien cache:', key);
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch : Stratégie hybride réseau/cache adaptée au mode PWA et à la lecture hors-ligne
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);

    // Ne pas intercepter l'administration Django ou les requêtes d'authentification sensibles
    if (url.pathname.startsWith('/django-admin/') || url.pathname.startsWith('/administration/')) {
        return;
    }

    // 1. FLUX SÉCURISÉ DES ÉPREUVES PDF (Stream watermarked & documents pédagogiques)
    // Réseau direct, avec repli instantané sur le cache PWA (DOCS_CACHE_NAME) si hors-ligne
    if (url.pathname.includes('/stream-watermarked/') || url.pathname.includes('/pdf/')) {
        event.respondWith(
            fetch(event.request).catch(() => {
                // Hors-ligne : servir immédiatement depuis le cache PWA des documents
                return caches.open(DOCS_CACHE_NAME).then((cache) => {
                    return cache.match(event.request).then((cachedResponse) => {
                        if (cachedResponse) {
                            return cachedResponse;
                        }
                        return new Response(
                            JSON.stringify({ error: "Ce document n'a pas encore été ouvert en ligne pour être disponible hors-ligne." }),
                            { status: 503, headers: { 'Content-Type': 'application/json' } }
                        );
                    });
                });
            })
        );
        return;
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
                        return caches.match('/').then((homeResponse) => {
                            return homeResponse || new Response(
                                '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Hors-ligne — ArchivEx</title></head><body style="font-family:sans-serif;text-align:center;padding:50px;background:#071A49;color:#fff;"><h2>Vous êtes hors-ligne</h2><p>Ce contenu sera accessible dès que vous l\'aurez consulté une première fois avec une connexion Internet.</p><button onclick="window.location.reload()" style="padding:10px 20px;border-radius:10px;background:#2563EB;color:#fff;border:none;cursor:pointer;">Réessayer</button></body></html>',
                                { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                            );
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