/**
 * ArchivEx PWA Controller (Service Worker Registration, Direct Install & Universal Guide)
 */

let deferredPrompt = null;
let pwaPopupTimer = null;

// 1. Détection de la plateforme et du mode d'affichage
const isIos = () => {
    const ua = window.navigator.userAgent.toLowerCase();
    return /iphone|ipad|ipod/.test(ua);
};

const isAndroid = () => {
    return /android/.test(window.navigator.userAgent.toLowerCase());
};

const isInStandaloneMode = () => {
    return ('standalone' in window.navigator && window.navigator.standalone) ||
           (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
           localStorage.getItem('archivex_pwa_installed') === 'true';
};

// 2. Enregistrement direct et immédiat du Service Worker
function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
            .then((registration) => {
                console.log('[PWA] Service Worker actif sur le scope:', registration.scope);
            })
            .catch((error) => {
                console.warn('[PWA] Échec d\'enregistrement du Service Worker:', error);
            });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', registerServiceWorker);
} else {
    registerServiceWorker();
}

// 3. Capture de l'événement natif avant invite d'installation
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    window.deferredPWAInstallPrompt = e;
    console.log('[PWA] beforeinstallprompt capturé et disponible');

    // Afficher la boîte de prompt direct dans le modal si ouvert
    const promptBox = document.getElementById('pwa-modal-prompt-box');
    if (promptBox) {
        promptBox.classList.remove('hidden');
    }

    // Assurer la visibilité de tout bouton ayant l'ID legacy installBtn
    const legacyBtn = document.getElementById('installBtn');
    if (legacyBtn) legacyBtn.style.display = 'inline-flex';

    updateInstallButtonsState(false);
});

// 4. Événement déclenché une fois l'application installée avec succès
window.addEventListener('appinstalled', () => {
    console.log('[PWA] ArchivEx a été installé avec succès sur cet appareil !');
    deferredPrompt = null;
    window.deferredPWAInstallPrompt = null;
    localStorage.setItem('archivex_pwa_installed', 'true');
    localStorage.setItem('archivex_pwa_dismissed', 'true');
    dismissPwaPopup(true);
    closePwaInstallModal();
    showPwaToast('ArchivEx est installé avec succès sur votre appareil !');
    updateInstallButtonsState(true);
});

// 5. Mise à jour de l'état textuel des boutons
function updateInstallButtonsState(isInstalled) {
    const triggers = document.querySelectorAll('.pwa-install-trigger, #installBtn');
    triggers.forEach(btn => {
        if (isInstalled || isInStandaloneMode()) {
            btn.setAttribute('data-installed', 'true');
            const span = btn.querySelector('span');
            if (span && !btn.id.includes('popup')) {
                span.textContent = 'App installée';
            }
        }
    });
}

// 6. Action d'installation principale déclenchée au clic
async function triggerPwaInstall() {
    // Cas 1 : Déjà dans l'application installée
    if (isInStandaloneMode()) {
        showPwaToast('Vous utilisez déjà l\'application ArchivEx !');
        return;
    }

    // Cas 2 : Le prompt natif est immédiatement disponible
    if (deferredPrompt) {
        await executeNativePwaPrompt();
        return;
    }

    // Cas 3 : Petite temporisation au cas où l'événement est en cours de dispatch
    await new Promise(resolve => setTimeout(resolve, 300));
    if (deferredPrompt) {
        await executeNativePwaPrompt();
        return;
    }

    // Cas 4 : Le prompt natif n'est pas fourni directement par le navigateur
    // (Ex: Safari iOS, Chrome desktop sans prompt immédiat, Firefox, etc.)
    openPwaInstallModal();
}

// 7. Exécution du prompt natif navigateur
async function executeNativePwaPrompt() {
    if (!deferredPrompt) return;

    try {
        deferredPrompt.prompt();
        const choiceResult = await deferredPrompt.userChoice;
        console.log('[PWA] Choix de l\'utilisateur:', choiceResult.outcome);

        if (choiceResult.outcome === 'accepted') {
            localStorage.setItem('archivex_pwa_installed', 'true');
            localStorage.setItem('archivex_pwa_dismissed', 'true');
            dismissPwaPopup(true);
            closePwaInstallModal();
            showPwaToast('Installation en cours...');
        }
    } catch (err) {
        console.error('[PWA] Erreur lors du prompt:', err);
    } finally {
        deferredPrompt = null;
        window.deferredPWAInstallPrompt = null;
    }
}

// 8. Gestion du modal d'installation universel
function openPwaInstallModal() {
    const modal = document.getElementById('pwa-install-modal');
    if (!modal) return;

    // Si le prompt natif est disponible, l'afficher en tête
    const promptBox = document.getElementById('pwa-modal-prompt-box');
    if (promptBox) {
        if (deferredPrompt) {
            promptBox.classList.remove('hidden');
        } else {
            promptBox.classList.add('hidden');
        }
    }

    // Sélectionner automatiquement l'onglet selon l'appareil
    if (isIos() || isAndroid()) {
        switchPwaTab('mobile');
    } else {
        switchPwaTab('desktop');
    }

    modal.classList.remove('hidden');
}

function closePwaInstallModal() {
    const modal = document.getElementById('pwa-install-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

function switchPwaTab(tab) {
    const tabMobile = document.getElementById('tab-content-mobile');
    const tabDesktop = document.getElementById('tab-content-desktop');
    const btnMobile = document.getElementById('tab-btn-mobile');
    const btnDesktop = document.getElementById('tab-btn-desktop');

    if (tab === 'mobile') {
        if (tabMobile) tabMobile.classList.remove('hidden');
        if (tabDesktop) tabDesktop.classList.add('hidden');
        if (btnMobile) {
            btnMobile.classList.add('bg-white', 'shadow-xs', 'text-[#071A49]');
            btnMobile.classList.remove('text-slate-500');
        }
        if (btnDesktop) {
            btnDesktop.classList.remove('bg-white', 'shadow-xs', 'text-[#071A49]');
            btnDesktop.classList.add('text-slate-500');
        }
    } else {
        if (tabMobile) tabMobile.classList.add('hidden');
        if (tabDesktop) tabDesktop.classList.remove('hidden');
        if (btnDesktop) {
            btnDesktop.classList.add('bg-white', 'shadow-xs', 'text-[#071A49]');
            btnDesktop.classList.remove('text-slate-500');
        }
        if (btnMobile) {
            btnMobile.classList.remove('bg-white', 'shadow-xs', 'text-[#071A49]');
            btnMobile.classList.add('text-slate-500');
        }
    }
}

// 9. Bannière Télécharger discrète (UNIQUEMENT première visite, plus jamais après rejet ou installation)
let pwaAutoDismissTimer = null;

function shouldShowPwaPopup() {
    // 1. Déjà en standalone ou déjà installée
    if (isInStandaloneMode()) return false;
    if (localStorage.getItem('archivex_pwa_installed') === 'true') return false;

    // 2. Déjà fermée ou refusée par l'utilisateur (définitif)
    if (localStorage.getItem('archivex_pwa_dismissed') === 'true') return false;
    if (sessionStorage.getItem('archivex_pwa_session_shown') === 'true') return false;

    return true;
}

function initPwaPopup() {
    if (!shouldShowPwaPopup()) {
        updateInstallButtonsState(isInStandaloneMode() || localStorage.getItem('archivex_pwa_installed') === 'true');
        return;
    }

    // Apparaît uniquement lors de la première découverte après 3 secondes
    pwaPopupTimer = setTimeout(() => {
        showPwaPopup();
    }, 3000);
}

function showPwaPopup() {
    if (!shouldShowPwaPopup()) return;

    const popup = document.getElementById('pwa-install-popup');
    if (popup) {
        sessionStorage.setItem('archivex_pwa_session_shown', 'true');
        popup.classList.remove('hidden');
        requestAnimationFrame(() => {
            popup.classList.remove('translate-y-10', 'opacity-0');
            popup.classList.add('translate-y-0', 'opacity-100');
        });
        console.log('[PWA] Bannière d\'installation affichée (première visite)');

        // Disparaît automatiquement au bout de 6 secondes
        clearTimeout(pwaAutoDismissTimer);
        pwaAutoDismissTimer = setTimeout(() => {
            dismissPwaPopup();
        }, 6000);

        // Pause de l'auto-dismiss au survol
        popup.addEventListener('mouseenter', () => {
            clearTimeout(pwaAutoDismissTimer);
        });
        popup.addEventListener('mouseleave', () => {
            pwaAutoDismissTimer = setTimeout(() => {
                dismissPwaPopup();
            }, 2000);
        });
    }
}

function dismissPwaPopup(isInstalled = false) {
    clearTimeout(pwaAutoDismissTimer);
    clearTimeout(pwaPopupTimer);

    // Mémoriser de façon DÉFINITIVE pour ne plus jamais embêter l'utilisateur
    localStorage.setItem('archivex_pwa_dismissed', 'true');
    sessionStorage.setItem('archivex_pwa_session_shown', 'true');

    if (isInstalled) {
        localStorage.setItem('archivex_pwa_installed', 'true');
    }

    const popup = document.getElementById('pwa-install-popup');
    if (popup) {
        popup.classList.remove('translate-y-0', 'opacity-100');
        popup.classList.add('translate-y-10', 'opacity-0');
        setTimeout(() => {
            popup.classList.add('hidden');
        }, 500);
    }
}

// 10. Toast utilitaire
function showPwaToast(message) {
    const toast = document.getElementById('pwa-toast');
    const msgEl = document.getElementById('pwa-toast-message');
    if (toast && msgEl) {
        msgEl.textContent = message;
        toast.classList.remove('hidden');
        toast.classList.add('flex');
        setTimeout(() => {
            toast.classList.add('hidden');
            toast.classList.remove('flex');
        }, 4000);
    }
}

// 11. Initialisation globale
document.addEventListener('DOMContentLoaded', () => {
    // Interception des clics sur tout bouton d'installation
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.pwa-install-trigger, #installBtn, [data-pwa-install]');
        if (trigger) {
            e.preventDefault();
            triggerPwaInstall();
        }
    });

    initPwaPopup();
});
