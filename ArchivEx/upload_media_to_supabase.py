import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from django.core.files.storage import default_storage

BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = BASE_DIR / "media"

lock = threading.Lock()
uploaded_count = 0
skipped_count = 0
error_count = 0

def upload_single_file(rel_path, local_path):
    global uploaded_count, skipped_count, error_count
    try:
        # Check if exists
        if default_storage.exists(rel_path):
            with lock:
                skipped_count += 1
            return "SKIPPED"
        
        with open(local_path, "rb") as f:
            default_storage.save(rel_path, f)
        
        with lock:
            uploaded_count += 1
            if uploaded_count % 250 == 0:
                print(f"[>] {uploaded_count} fichiers envoyés...", flush=True)
        return "OK"
    except Exception as e:
        with lock:
            error_count += 1
        return f"ERROR: {e}"

def main():
    if not settings.USE_SUPABASE_STORAGE:
        print("[!] ATTENTION : USE_SUPABASE_STORAGE est à False dans .env.")
        return

    if not MEDIA_ROOT.exists():
        print("[-] Aucun dossier media/ local trouvé.")
        return

    print("=== COLLECTE DES FICHIERS LOCAUX ===")
    all_files = []
    for root, dirs, files in os.walk(MEDIA_ROOT):
        for file in files:
            local_path = Path(root) / file
            rel_path = local_path.relative_to(MEDIA_ROOT).as_posix()
            all_files.append((rel_path, local_path))

    total = len(all_files)
    print(f"Total fichiers trouvés : {total}")
    print(f"Bucket cible : {settings.AWS_STORAGE_BUCKET_NAME}")
    print("Démarrage du téléversement parallèle (16 threads)...", flush=True)

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(upload_single_file, rel_path, local_path) for rel_path, local_path in all_files]
        for f in as_completed(futures):
            pass

    print(f"\n=== SYNCHRONISATION TERMINEE ===")
    print(f"Envoyés : {uploaded_count}")
    print(f"Déjà présents (ignorés) : {skipped_count}")
    print(f"Erreurs : {error_count}")
    print(f"Total vérifié : {total}")

if __name__ == "__main__":
    main()
