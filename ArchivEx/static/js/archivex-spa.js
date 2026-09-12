/**
 * ArchivEx SPA Router & Smooth Navigation Engine
 * Fournit une expérience applicative instantanée, fluide (style WhatsApp / App native) :
 * - Navigation sans rechargement complet de page (évite l'écran blanc et le saut brutal au sommet)
 * - Préchargement instantané au toucher (touchstart) ou survol (mouseenter)
 * - Maintien et restauration précise du défilement (scroll) lors du retour en arrière
 * - Barre de progression de chargement ultra-fine et discrète
 * - Exécution propre des scripts de vue injectés
 */

(function() {
    'use strict';

    // Empêcher l'initialisation multiple
    if (window.__ARCHIVEX_SPA_INITIALIZED__) return;
    window.__ARCHIVEX_SPA_INITIALIZED__ = true;

    const CACHE_MAX_AGE_MS = 60 * 1000; // 60 secondes de cache en mémoire
    const pageCache = new Map();
    const scrollPositions = new Map();

    // 1. Barre de progression supérieure
    let progressBar = document.getElementById('spa-progress-bar');
    if (!progressBar) {
        progressBar = document.createElement('div');
        progressBar.id = 'spa-progress-bar';
        progressBar.setAttribute('aria-hidden', 'true');
        progressBar.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            height: 2.5px;
            width: 0%;
            background: linear-gradient(90deg, #2563EB, #38BDF8, #10B981);
            z-index: 999999;
            transition: width 0.22s ease-out, opacity 0.25s ease-in-out;
            opacity: 0;
            pointer-events: none;
            box-shadow: 0 1px 6px rgba(37, 99, 235, 0.4);
        `;
        document.documentElement.appendChild(progressBar);
    }

    let progressTimer = null;

    function startProgress() {
        if (progressTimer) clearInterval(progressTimer);
        progressBar.style.opacity = '1';
        progressBar.style.width = '20%';

        let currentWidth = 20;
        progressTimer = setInterval(() => {
            if (currentWidth < 85) {
                currentWidth += Math.random() * 15;
                progressBar.style.width = Math.min(currentWidth, 85) + '%';
            }
        }, 120);
    }

    function stopProgress() {
        if (progressTimer) {
            clearInterval(progressTimer);
            progressTimer = null;
        }
        progressBar.style.width = '100%';
        setTimeout(() => {
            progressBar.style.opacity = '0';
            setTimeout(() => {
                progressBar.style.width = '0%';
            }, 250);
        }, 150);
    }

    // 2. Détection des liens éligibles
    function isEligibleLink(anchor) {
        if (!anchor || anchor.tagName !== 'A') return false;
        if (!anchor.href) return false;
        if (anchor.target && anchor.target !== '_self') return false;
        if (anchor.hasAttribute('download')) return false;
        if (anchor.hasAttribute('data-no-spa') || anchor.hasAttribute('data-native')) return false;

        // Même origine obligatoire
        try {
            const url = new URL(anchor.href, window.location.origin);
            if (url.origin !== window.location.origin) return false;

            const path = url.pathname.toLowerCase();

            // Exclure les zones d'administration et d'authentification sensible
            if (path.startsWith('/django-admin/') || path.startsWith('/administration/')) return false;
            if (path.includes('/logout') || path.includes('/deconnexion')) return false;

            // Exclure les fichiers statiques, médias et téléchargements directs
            if (path.startsWith('/static/') || path.startsWith('/media/')) return false;
            if (/\.(pdf|zip|rar|docx?|xlsx?|pptx?|jpe?g|png|gif|svg|webp|mp4|mp3)$/i.test(path)) return false;

            return true;
        } catch (e) {
            return false;
        }
    }

    // 3. Préchargement en mémoire (Prefetch)
    function prefetchUrl(urlStr) {
        try {
            const url = new URL(urlStr, window.location.origin);
            const key = url.pathname + url.search;
            const cached = pageCache.get(key);
            if (cached && (Date.now() - cached.time < CACHE_MAX_AGE_MS)) {
                return; // Déjà en cache frais
            }

            fetch(url.href, {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'ArchivEx-SPA',
                    'Accept': 'text/html'
                },
                credentials: 'same-origin'
            })
            .then(res => {
                if (res.ok && res.headers.get('content-type')?.includes('text/html')) {
                    return res.text();
                }
                return null;
            })
            .then(html => {
                if (html) {
                    pageCache.set(key, { html, time: Date.now() });
                }
            })
            .catch(() => {
                // Erreur silencieuse en prefetch
            });
        } catch (e) {}
    }

    // 4. Navigation SPA principale
    async function navigateTo(urlStr, options = {}) {
        const { pushState = true, scrollToTop = true, targetHash = null } = options;

        try {
            const targetUrl = new URL(urlStr, window.location.origin);
            const currentUrl = new URL(window.location.href);

            // Si c'est juste un changement de hash sur la même page
            if (targetUrl.pathname === currentUrl.pathname && targetUrl.search === currentUrl.search) {
                if (targetUrl.hash) {
                    const el = document.querySelector(targetUrl.hash);
                    if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        if (pushState) history.pushState(null, '', targetUrl.href);
                        return;
                    }
                }
            }

            // Sauvegarder la position de défilement actuelle avant de quitter
            scrollPositions.set(currentUrl.pathname + currentUrl.search, window.scrollY);

            const cacheKey = targetUrl.pathname + targetUrl.search;
            let htmlContent = null;
            const cached = pageCache.get(cacheKey);

            if (cached && (Date.now() - cached.time < CACHE_MAX_AGE_MS)) {
                htmlContent = cached.html;
            } else {
                startProgress();
                const res = await fetch(targetUrl.href, {
                    method: 'GET',
                    headers: {
                        'X-Requested-With': 'ArchivEx-SPA',
                        'Accept': 'text/html'
                    },
                    credentials: 'same-origin'
                });

                if (!res.ok) {
                    stopProgress();
                    window.location.href = targetUrl.href;
                    return;
                }

                // Vérifier si le serveur a redirigé vers une URL externe
                const finalUrl = new URL(res.url, window.location.origin);
                if (finalUrl.origin !== window.location.origin) {
                    window.location.href = res.url;
                    return;
                }

                htmlContent = await res.text();
                pageCache.set(cacheKey, { html: htmlContent, time: Date.now() });
            }

            const parser = new DOMParser();
            const newDoc = parser.parseFromString(htmlContent, 'text/html');

            const currentMain = document.getElementById('main-content');
            const newMain = newDoc.getElementById('main-content');

            if (!currentMain || !newMain) {
                // Si la page cible n'a pas de #main-content (ex: page d'erreur ou admin), fallback natif
                stopProgress();
                window.location.href = targetUrl.href;
                return;
            }

            // Mise à jour du titre de la page
            if (newDoc.title) {
                document.title = newDoc.title;
            }

            // Remplacement fluide du contenu principal
            currentMain.style.opacity = '0.94';
            currentMain.innerHTML = newMain.innerHTML;

            // Ré-exécuter les scripts présents dans le nouveau main
            const scripts = currentMain.querySelectorAll('script');
            scripts.forEach(oldScript => {
                const newScript = document.createElement('script');
                Array.from(oldScript.attributes).forEach(attr => newScript.setAttribute(attr.name, attr.value));
                newScript.textContent = oldScript.textContent;
                oldScript.parentNode.replaceChild(newScript, oldScript);
            });

            // Mettre à jour l'historique
            if (pushState) {
                history.pushState({ spa: true, url: targetUrl.href }, '', targetUrl.href);
            }

            // Gestion du défilement
            if (targetHash || targetUrl.hash) {
                const hashSelector = targetHash || targetUrl.hash;
                const targetElement = document.querySelector(hashSelector);
                if (targetElement) {
                    targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
                } else if (scrollToTop) {
                    window.scrollTo({ top: 0, behavior: 'instant' });
                }
            } else if (scrollToTop) {
                window.scrollTo({ top: 0, behavior: 'instant' });
            }

            // Rétablir l'opacité
            requestAnimationFrame(() => {
                currentMain.style.opacity = '1';
            });

            stopProgress();

            // Fermer tout menu mobile ou sheet éventuellement resté ouvert
            const mobileMenu = document.getElementById('mobile-menu');
            if (mobileMenu && !mobileMenu.classList.contains('hidden')) {
                mobileMenu.classList.add('hidden');
            }
            const resSheet = document.getElementById('mobile-resources-sheet');
            if (resSheet && !resSheet.classList.contains('hidden')) {
                resSheet.classList.add('hidden');
            }

            // Mettre à jour l'état actif de la barre de navigation mobile du bas (Dock)
            document.querySelectorAll('.dock-item').forEach(item => {
                const href = item.getAttribute('href');
                if (href) {
                    try {
                        const itemUrl = new URL(href, window.location.origin);
                        if (itemUrl.pathname === targetUrl.pathname) {
                            item.classList.add('dock-item-active');
                        } else {
                            item.classList.remove('dock-item-active');
                        }
                    } catch (e) {}
                }
            });

            // Déclencher un événement global pour que les composants de la page se réinitialisent
            window.dispatchEvent(new CustomEvent('archivex:page-loaded', {
                detail: { url: targetUrl.href }
            }));

            // Si un script de liste d'épreuves est présent sur la nouvelle page, exécuter l'auto-ouverture
            initPageSpecificHooks();

        } catch (error) {
            console.error('[ArchivEx SPA] Erreur de transition:', error);
            stopProgress();
            window.location.href = urlStr;
        }
    }

    // 5. Hooks spécifiques par page
    function initPageSpecificHooks() {
        // Auto-dépliage des cartes UE si hash présent
        if (window.location.hash && window.location.hash.startsWith('#ue-card-')) {
            const ueId = window.location.hash.replace('#ue-card-', '');
            if (typeof window.toggleUeYears === 'function') {
                window.toggleUeYears(ueId);
                const card = document.getElementById('ue-card-' + ueId);
                if (card) {
                    setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
                }
            }
        }
    }

    // 6. Gestion du retour arrière / avant (popstate)
    window.addEventListener('popstate', (e) => {
        const url = window.location.href;
        const currentUrlObj = new URL(url);
        const savedScroll = scrollPositions.get(currentUrlObj.pathname + currentUrlObj.search) || 0;

        navigateTo(url, { pushState: false, scrollToTop: false }).then(() => {
            window.scrollTo({ top: savedScroll, behavior: 'instant' });
        });
    });

    // 7. Écouteur global des clics sur les liens
    document.addEventListener('click', (e) => {
        // Clics avec touches modificatrices : comportement par défaut
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
            return;
        }

        const anchor = e.target.closest('a');
        if (!anchor) return;

        if (isEligibleLink(anchor)) {
            e.preventDefault();
            navigateTo(anchor.href, { pushState: true });
        }
    }, true);

    // 8. Écouteur des formulaires de recherche GET (ex: filtres et barres de recherche)
    document.addEventListener('submit', (e) => {
        const form = e.target;
        if (!form || form.tagName !== 'FORM') return;
        if (form.method.toUpperCase() !== 'GET') return;
        if (form.hasAttribute('data-no-spa')) return;

        try {
            const actionUrl = new URL(form.action || window.location.href, window.location.origin);
            if (actionUrl.origin !== window.location.origin) return;

            const formData = new FormData(form);
            const params = new URLSearchParams();
            for (const [k, v] of formData.entries()) {
                if (v) params.append(k, v);
            }

            const targetUrl = actionUrl.pathname + (params.toString() ? '?' + params.toString() : '');
            e.preventDefault();
            navigateTo(targetUrl, { pushState: true, scrollToTop: false });
        } catch (err) {
            // Laisser le formulaire faire son submit naturel en cas d'erreur
        }
    });

    // 9. Préchargement intelligent au survol (desktop) et au touchstart (mobile)
    let prefetchTimeout = null;

    document.addEventListener('pointerenter', (e) => {
        const anchor = e.target?.closest?.('a');
        if (!anchor || !isEligibleLink(anchor)) return;

        prefetchTimeout = setTimeout(() => {
            prefetchUrl(anchor.href);
        }, 60);
    }, true);

    document.addEventListener('pointerleave', (e) => {
        if (prefetchTimeout) {
            clearTimeout(prefetchTimeout);
            prefetchTimeout = null;
        }
    }, true);

    document.addEventListener('touchstart', (e) => {
        const anchor = e.target?.closest?.('a');
        if (!anchor || !isEligibleLink(anchor)) return;
        prefetchUrl(anchor.href);
    }, { passive: true, capture: true });

    // Initialisation au premier chargement
    document.addEventListener('DOMContentLoaded', () => {
        initPageSpecificHooks();
    });

    // Exposer l'API publiquement
    window.ArchivExSPA = {
        navigate: navigateTo,
        prefetch: prefetchUrl,
        clearCache: () => pageCache.clear()
    };

})();
