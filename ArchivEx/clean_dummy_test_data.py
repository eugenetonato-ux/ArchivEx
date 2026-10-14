import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from academics.models import Subject, Filiere, Semester
from exams.models import Exam
from content.models import CloudFile, Summary

DUMMY_PATTERNS = [
    'algo_free', 'sql_prem', 'test', 'draft', 'physique', 'orig', 'resume_algo',
    'statistique_2025-2026_ohsljwe', 'microeconomie_2025-2026_tpya5uc',
    'corr_free', 'corr_premium', 'sum_free', 'sum_premium',
    'microeconomie_2025-2026_corrige', 'microeconomie_2025-2026_1om3gux',
    'statistique_2025-2026.pdf', 'microeconomie_2025-2026.pdf'
]

def is_dummy_file(path_or_str):
    name = Path(path_or_str).name.lower()
    if any(p in name for p in DUMMY_PATTERNS):
        return True
    if name in ['ep.pdf', 'co.pdf', 'su.pdf', 'epreuve.pdf', 'correction.pdf', 'summary.pdf']:
        return True
    if name.startswith('ep_') or name.startswith('co_') or name.startswith('su_') or name.startswith('micro_2025'):
        return True
    if 'correction_' in name or 'epreuve_' in name or 'summary_' in name:
        return True
    return False

def clean_media_files():
    print("\n--- 1. NETTOYAGE DES FICHIERS TESTS DANS MEDIA/ ---")
    media_dir = Path(settings.MEDIA_ROOT)
    removed_count = 0
    
    # Parcourir media
    for f in list(media_dir.rglob('*.*')):
        if f.is_file() and is_dummy_file(f):
            try:
                f.unlink()
                removed_count += 1
            except Exception as e:
                print(f"  Erreur lors de la suppression de {f}: {e}")
                
    # Nettoyer aussi le dossier cloud_library (uniquement des fichiers tests de 20 octets)
    cloud_dir = media_dir / 'cloud_library'
    if cloud_dir.exists():
        for f in list(cloud_dir.rglob('*.*')):
            if f.is_file():
                try:
                    f.unlink()
                    removed_count += 1
                except Exception as e:
                    pass

    # Vider le cache de PDFs filigranés
    cache_dir = media_dir / 'cache'
    if cache_dir.exists():
        for f in list(cache_dir.rglob('*.pdf')):
            if f.is_file():
                try:
                    f.unlink()
                    removed_count += 1
                except Exception as e:
                    pass

    print(f"[+] {removed_count} fichier(s) média de test supprimé(s) du disque.")

def clean_database():
    print("\n--- 2. NETTOYAGE DE LA BASE DE DONNÉES ---")
    
    # 1. Épreuves factices
    dummy_exams = []
    for exam in Exam.objects.all():
        fn = os.path.basename(str(exam.file or ''))
        cfn = os.path.basename(str(exam.correction_file or ''))
        title = exam.title or ''
        if is_dummy_file(fn) or is_dummy_file(cfn) or any(p in title.lower() for p in ['algo free', 'sql premium', 'draft', 'physique', 'epreuve', 'orig exam', 'test']):
            dummy_exams.append(exam.id)
            
    deleted_exams, _ = Exam.objects.filter(id__in=dummy_exams).delete()
    print(f"[*] {deleted_exams} épreuve(s) factice(s) supprimée(s) de la base.")

    # 2. Fichiers Cloud factices
    dummy_cfs = []
    for cf in CloudFile.objects.all():
        fn = os.path.basename(str(cf.file or ''))
        title = cf.title or ''
        if is_dummy_file(fn) or any(p in title.lower() for p in ['algo free', 'sql premium', 'draft', 'physique', 'epreuve', 'orig exam', 'test']):
            dummy_cfs.append(cf.id)
            
    deleted_cfs, _ = CloudFile.objects.filter(id__in=dummy_cfs).delete()
    print(f"[*] {deleted_cfs} fichier(s) Cloud factice(s) supprimé(s).")

    # 3. Résumés factices
    dummy_sums = []
    for sm in Summary.objects.all():
        fn = os.path.basename(str(sm.file or ''))
        title = sm.title or ''
        if is_dummy_file(fn) or any(p in title.lower() for p in ['algo', 'sql', 'test', 'draft']):
            dummy_sums.append(sm.id)
            
    deleted_sums, _ = Summary.objects.filter(id__in=dummy_sums).delete()
    print(f"[*] {deleted_sums} résumé(s) factice(s) supprimé(s).")

    # 4. Matières factices (créées automatiquement lors des tests ou sans épreuve)
    dummy_subjects = []
    for subj in Subject.objects.all():
        name = subj.name.lower()
        if any(p in name for p in ['algo free', 'sql prem', 'draft', 'test', 'epreuve', 'orig exam', 'physique', 'micro 2025', 'statistique 2025-2026 ohsljwe']):
            dummy_subjects.append(subj.id)
        elif subj.exams.count() == 0 and subj.summaries.count() == 0 and any(h in subj.name for h in [' ', '_']):
            # Vérifier si c'est un nom généré avec un hash aléatoire
            parts = subj.name.split()
            if any(len(p) == 7 and p.isalnum() for p in parts):
                dummy_subjects.append(subj.id)
                
    deleted_subjects, _ = Subject.objects.filter(id__in=dummy_subjects).delete()
    print(f"[*] {deleted_subjects} matière(s) factice(s) supprimée(s).")

if __name__ == '__main__':
    print("=== Démarrage du nettoyage des données de test ArchivEx ===")
    clean_media_files()
    clean_database()
    print("\n=== Nettoyage terminé avec succès ! ===")
