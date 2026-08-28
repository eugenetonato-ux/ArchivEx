/**
 * ArchivEx — Système de Glisser-Déposer (Drag & Drop) pour Fichiers
 * Transforme automatiquement les champs <input type="file"> en zones de dépôts interactives.
 */

document.addEventListener('DOMContentLoaded', function () {
    initDragAndDropUploads();
});

function initDragAndDropUploads() {
    const fileInputs = document.querySelectorAll('input[type="file"]');

    fileInputs.forEach(input => {
        // Éviter d'initialiser deux fois la même zone
        if (input.dataset.dragDropInitialized) return;
        input.dataset.dragDropInitialized = "true";

        // Créer la zone réceptrice d'animation
        const wrapper = document.createElement('div');
        wrapper.className = 'drag-drop-zone relative border-2 border-dashed border-slate-300 hover:border-[#2563EB] bg-slate-50/60 hover:bg-blue-50/40 rounded-2xl p-5 text-center transition-all duration-200 cursor-pointer group my-2';

        // Masquer le champ input classique tout en le maintenant fonctionnel dans le DOM
        input.classList.add('sr-only');

        // Insérer le conteneur visuel
        const parent = input.parentNode;
        parent.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        // Contenu visuel de la zone de dépôt
        const contentDiv = document.createElement('div');
        contentDiv.className = 'drag-drop-content space-y-2 pointer-events-none';

        contentDiv.innerHTML = `
            <div class="w-12 h-12 rounded-2xl bg-blue-100/80 group-hover:bg-[#2563EB] text-[#2563EB] group-hover:text-white flex items-center justify-center mx-auto transition-all transform group-hover:scale-110 shadow-xs">
                <i class="fa-solid fa-cloud-arrow-up text-xl" aria-hidden="true"></i>
            </div>
            <div>
                <p class="text-xs font-extrabold text-[#071A49] group-hover:text-[#2563EB] transition-colors">
                    Glissez-déposez votre fichier ici <span class="text-slate-400 font-normal">ou</span> <span class="text-[#2563EB] underline">Parcourir</span>
                </p>
                <p class="text-[11px] text-slate-400 font-medium mt-0.5 drag-drop-hint">
                    Formats acceptés : PDF, Word, Images (max. 50 Mo)
                </p>
            </div>
            <div class="selected-file-info hidden pt-1">
                <div class="inline-flex items-center space-x-2 bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-1.5 rounded-xl text-xs font-bold shadow-2xs">
                    <i class="fa-solid fa-file-pdf text-rose-500 text-sm"></i>
                    <span class="file-name truncate max-w-[200px] sm:max-w-[280px]">aucun fichier</span>
                    <span class="file-size text-[10px] text-emerald-600 font-semibold"></span>
                    <i class="fa-solid fa-circle-check text-emerald-500 ml-1"></i>
                </div>
            </div>
        `;

        wrapper.appendChild(contentDiv);

        const fileNameSpan = contentDiv.querySelector('.file-name');
        const fileSizeSpan = contentDiv.querySelector('.file-size');
        const selectedInfoDiv = contentDiv.querySelector('.selected-file-info');

        function updateFilePreview(file) {
            if (file) {
                fileNameSpan.textContent = file.name;
                const sizeInMB = (file.size / (1024 * 1024)).toFixed(2);
                fileSizeSpan.textContent = `(${sizeInMB > 1 ? sizeInMB + ' Mo' : Math.round(file.size / 1024) + ' Ko'})`;
                selectedInfoDiv.classList.remove('hidden');
                wrapper.classList.add('border-emerald-400', 'bg-emerald-50/30');
                wrapper.classList.remove('border-slate-300');
            } else {
                selectedInfoDiv.classList.add('hidden');
                wrapper.classList.remove('border-emerald-400', 'bg-emerald-50/30');
                wrapper.classList.add('border-slate-300');
            }
        }

        // Clic sur la zone de dépôt pour ouvrir l'explorateur de fichiers
        wrapper.addEventListener('click', function (e) {
            if (e.target !== input) {
                input.click();
            }
        });

        // Événement de changement via sélection manuelle
        input.addEventListener('change', function () {
            if (input.files && input.files.length > 0) {
                updateFilePreview(input.files[0]);
            }
        });

        // Gestion des événements du Glisser-Déposer (Drag & Drop)
        ['dragenter', 'dragover'].forEach(eventName => {
            wrapper.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                wrapper.classList.add('border-[#2563EB]', 'bg-blue-100/60', 'ring-4', 'ring-blue-100', 'scale-[1.01]');
            }, false);
        });

        ['dragleave', 'dragend', 'drop'].forEach(eventName => {
            wrapper.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                wrapper.classList.remove('border-[#2563EB]', 'bg-blue-100/60', 'ring-4', 'ring-blue-100', 'scale-[1.01]');
            }, false);
        });

        wrapper.addEventListener('drop', function (e) {
            const dt = e.dataTransfer;
            const files = dt.files;

            if (files && files.length > 0) {
                input.files = files;
                updateFilePreview(files[0]);
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }, false);
    });
}
