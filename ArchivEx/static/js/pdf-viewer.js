/**
 * ArchivEx Universal Secure PDF Viewer (Mobile & Desktop)
 * Renders PDFs directly in the browser using PDF.js without leaving the site or triggering external downloads.
 */

(function() {
    'use strict';

    const PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
    const PDFJS_WORKER_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

    let pdfjsLoadingPromise = null;

    function loadPdfJs() {
        if (window.pdfjsLib) {
            return Promise.resolve(window.pdfjsLib);
        }
        if (pdfjsLoadingPromise) {
            return pdfjsLoadingPromise;
        }
        pdfjsLoadingPromise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = PDFJS_CDN;
            script.onload = () => {
                if (window.pdfjsLib) {
                    window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_CDN;
                    resolve(window.pdfjsLib);
                } else {
                    reject(new Error('PDF.js non disponible après chargement.'));
                }
            };
            script.onerror = () => reject(new Error('Impossible de charger PDF.js.'));
            document.head.appendChild(script);
        });
        return pdfjsLoadingPromise;
    }

    class ArchivexPdfViewer {
        constructor(container, url, options = {}) {
            this.container = typeof container === 'string' ? document.getElementById(container) : container;
            this.url = url;
            this.options = Object.assign({
                watermarkText: '',
                studentName: '',
                showControls: true,
                initialScale: 'page-width',
                maxDevicePixelRatio: 2.5
            }, options);

            this.pdfDoc = null;
            this.pageNum = 1;
            this.numPages = 0;
            this.scale = 1.0;
            this.scaleMode = 'page-width'; // 'page-width', 'page-fit', or number
            this.rendering = false;

            this.init();
        }

        init() {
            if (!this.container) return;
            this.container.innerHTML = '';
            this.container.classList.add('archivex-pdf-viewer-root');

            this.buildUI();
            this.loadDocument();
        }

        buildUI() {
            // Main structure
            this.rootWrapper = document.createElement('div');
            this.rootWrapper.className = 'w-full h-full flex flex-col bg-slate-900 text-slate-100 relative select-none';

            // Toolbar
            if (this.options.showControls) {
                this.toolbar = document.createElement('div');
                this.toolbar.className = 'bg-[#071A49] border-b border-blue-900/60 px-3 py-2 flex items-center justify-between gap-2 shrink-0 text-xs font-bold z-20 overflow-x-auto';
                this.toolbar.innerHTML = `
                    <div class="flex items-center space-x-1.5 shrink-0">
                        <button type="button" class="pdf-btn-prev px-2.5 py-1.5 rounded-lg bg-blue-950 hover:bg-blue-800 text-white border border-blue-700/50 flex items-center space-x-1 transition-all" title="Page précédente">
                            <i class="fa-solid fa-chevron-left text-[10px]"></i>
                            <span class="hidden sm:inline">Préc.</span>
                        </button>
                        <span class="text-xs font-black text-white px-2 py-1 bg-blue-950/80 rounded-lg border border-blue-800/60 whitespace-nowrap">
                            <span class="pdf-cur-page font-black text-amber-300">1</span> / <span class="pdf-total-pages">1</span>
                        </span>
                        <button type="button" class="pdf-btn-next px-2.5 py-1.5 rounded-lg bg-blue-950 hover:bg-blue-800 text-white border border-blue-700/50 flex items-center space-x-1 transition-all" title="Page suivante">
                            <span class="hidden sm:inline">Suiv.</span>
                            <i class="fa-solid fa-chevron-right text-[10px]"></i>
                        </button>
                    </div>

                    <div class="flex items-center space-x-1.5 shrink-0">
                        <button type="button" class="pdf-btn-zoom-out w-8 h-8 rounded-lg bg-blue-950 hover:bg-blue-800 text-white border border-blue-700/50 flex items-center justify-center transition-all" title="Zoom -">
                            <i class="fa-solid fa-magnifying-glass-minus text-xs"></i>
                        </button>
                        <button type="button" class="pdf-btn-fit-width px-2.5 py-1.5 rounded-lg bg-blue-950 hover:bg-blue-800 text-white border border-blue-700/50 text-[11px] font-extrabold transition-all" title="Ajuster à l'écran">
                            <i class="fa-solid fa-arrows-left-right text-[10px] mr-1"></i>
                            <span>Ajuster</span>
                        </button>
                        <button type="button" class="pdf-btn-zoom-in w-8 h-8 rounded-lg bg-blue-950 hover:bg-blue-800 text-white border border-blue-700/50 flex items-center justify-center transition-all" title="Zoom +">
                            <i class="fa-solid fa-magnifying-glass-plus text-xs"></i>
                        </button>
                    </div>
                `;
                this.rootWrapper.appendChild(this.toolbar);

                // Attach Toolbar Events
                this.toolbar.querySelector('.pdf-btn-prev').addEventListener('click', () => this.prevPage());
                this.toolbar.querySelector('.pdf-btn-next').addEventListener('click', () => this.nextPage());
                this.toolbar.querySelector('.pdf-btn-zoom-in').addEventListener('click', () => this.zoom(0.2));
                this.toolbar.querySelector('.pdf-btn-zoom-out').addEventListener('click', () => this.zoom(-0.2));
                this.toolbar.querySelector('.pdf-btn-fit-width').addEventListener('click', () => {
                    this.scaleMode = 'page-width';
                    this.renderCurrentPage();
                });
            }

            // Viewport Scroll Container (Quasi plein écran, défilement fluide)
            this.scrollContainer = document.createElement('div');
            this.scrollContainer.className = 'flex-grow overflow-auto p-1 sm:p-2 flex flex-col items-center bg-slate-950 relative';
            this.scrollContainer.style.webkitOverflowScrolling = 'touch';

            // Loading state
            this.loadingElem = document.createElement('div');
            this.loadingElem.className = 'absolute inset-0 z-30 bg-slate-900/90 flex flex-col items-center justify-center p-6 text-center';
            this.loadingElem.innerHTML = `
                <div class="w-10 h-10 border-4 border-blue-400 border-t-[#2563EB] rounded-full animate-spin mb-3"></div>
                <p class="text-xs font-black text-white">Chargement du document sécurisé...</p>
                <p class="text-[10px] text-slate-400 mt-1">Génération du tatouage numérique en cours</p>
            `;
            this.scrollContainer.appendChild(this.loadingElem);

            // Canvas wrapper
            this.canvasWrapper = document.createElement('div');
            this.canvasWrapper.className = 'relative shadow-2xl rounded-lg overflow-hidden bg-white my-auto max-w-full';
            
            this.canvas = document.createElement('canvas');
            this.canvas.className = 'block mx-auto max-w-full';
            this.canvasWrapper.appendChild(this.canvas);

            this.scrollContainer.appendChild(this.canvasWrapper);
            this.rootWrapper.appendChild(this.scrollContainer);
            this.container.appendChild(this.rootWrapper);
        }

        async loadDocument() {
            try {
                const pdfjs = await loadPdfJs();
                
                const loadingTask = pdfjs.getDocument({
                    url: this.url,
                    withCredentials: true,
                    cMapUrl: 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/cmaps/',
                    cMapPacked: true,
                });

                this.pdfDoc = await loadingTask.promise;
                this.numPages = this.pdfDoc.numPages;

                if (this.toolbar) {
                    const totalElem = this.toolbar.querySelector('.pdf-total-pages');
                    if (totalElem) totalElem.textContent = this.numPages;
                }

                if (this.loadingElem) {
                    this.loadingElem.remove();
                }

                await this.renderCurrentPage();

                // Window resize handler (debounced)
                let resizeTimer;
                window.addEventListener('resize', () => {
                    clearTimeout(resizeTimer);
                    resizeTimer = setTimeout(() => {
                        if (this.scaleMode === 'page-width') {
                            this.renderCurrentPage();
                        }
                    }, 200);
                });

            } catch (err) {
                console.error('Erreur chargement PDF:', err);
                if (this.loadingElem) {
                    this.loadingElem.innerHTML = `
                        <div class="w-12 h-12 rounded-2xl bg-rose-500/20 text-rose-400 flex items-center justify-center text-xl mb-3">
                            <i class="fa-solid fa-triangle-exclamation"></i>
                        </div>
                        <p class="text-xs font-black text-white mb-2">Impossible de charger le document</p>
                        <p class="text-[11px] text-slate-300 max-w-xs mb-4">Veuillez vérifier votre connexion ou votre Pass Semestre.</p>
                        <button type="button" class="px-4 py-2 bg-[#2563EB] hover:bg-blue-600 text-white rounded-xl text-xs font-black" onclick="location.reload()">
                            Réessayer
                        </button>
                    `;
                }
            }
        }

        async renderCurrentPage() {
            if (!this.pdfDoc || this.rendering) return;
            this.rendering = true;

            try {
                const page = await this.pdfDoc.getPage(this.pageNum);
                
                // Calculate Scale (Maximise l'espace sombre pour une lecture sans contrainte)
                const unscaledViewport = page.getViewport({ scale: 1.0 });
                const containerWidth = Math.max(300, (this.scrollContainer.clientWidth || window.innerWidth) - 10);

                if (this.scaleMode === 'page-width') {
                    this.scale = containerWidth / unscaledViewport.width;
                }

                // High DPI display sharpness
                const pixelRatio = Math.min(window.devicePixelRatio || 1, this.options.maxDevicePixelRatio);
                const viewport = page.getViewport({ scale: this.scale });

                this.canvas.width = Math.floor(viewport.width * pixelRatio);
                this.canvas.height = Math.floor(viewport.height * pixelRatio);
                this.canvas.style.width = Math.floor(viewport.width) + 'px';
                this.canvas.style.height = Math.floor(viewport.height) + 'px';

                const ctx = this.canvas.getContext('2d');
                ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

                const renderContext = {
                    canvasContext: ctx,
                    viewport: viewport
                };

                await page.render(renderContext).promise;

                // Update page number in UI
                if (this.toolbar) {
                    const curElem = this.toolbar.querySelector('.pdf-cur-page');
                    if (curElem) curElem.textContent = this.pageNum;
                }

                // Scroll to top of page
                this.scrollContainer.scrollTop = 0;

            } catch (err) {
                console.error('Erreur rendu page PDF:', err);
            } finally {
                this.rendering = false;
            }
        }

        prevPage() {
            if (this.pageNum <= 1) return;
            this.pageNum--;
            this.renderCurrentPage();
        }

        nextPage() {
            if (!this.pdfDoc || this.pageNum >= this.numPages) return;
            this.pageNum++;
            this.renderCurrentPage();
        }

        zoom(delta) {
            this.scaleMode = 'custom';
            this.scale = Math.max(0.4, Math.min(3.0, this.scale + delta));
            this.renderCurrentPage();
        }
    }

    // Expose Globally
    window.ArchivexPdfViewer = ArchivexPdfViewer;
    window.initArchivexPdfViewer = function(containerId, pdfUrl, options) {
        return new ArchivexPdfViewer(containerId, pdfUrl, options);
    };

})();
