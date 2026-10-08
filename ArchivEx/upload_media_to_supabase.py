"""
Script de synchronisation des fichiers locaux vers Supabase Storage (S3).

Usage :
    python upload_media_to_supabase.py              # Tout media/
    python upload_media_to_supabase.py exams/       # Sous-dossier spécifique
    python upload_media_to_supabase.py --dry-run    # Simulation sans upload

IMPORTANT : Ce script utilise boto3 PUT direct pour contourner le bug
Supabase S3 qui retourne 400 Bad Request sur HeadObject (utilisé par
django-storages pour vérifier l'existence d'un fichier).
"""

import os
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.conf import settings
import boto3
import unicodedata
import re
from botocore.exceptions import ClientError

BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = BASE_DIR / "media"

lock = threading.Lock()
uploaded_count = 0
error_count = 0


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
    )

def sanitize_key(key):
    """
    Translitere les accents et normalise le nom de fichier pour Supabase S3.
    Ex: 'Analyse mathematique.pdf' -> 'Analyse_mathematique.pdf'
    Seuls les segments de chemin (filename) sont modifies, pas les dossiers.
    """
    parts = key.replace("\\", "/").split("/")
    sanitized_parts = []
    for i, part in enumerate(parts):
        if i < len(parts) - 1:
            # Dossiers : on garde tel quel (2024-2025, S1, etc.)
            sanitized_parts.append(part)
        else:
            # Nom de fichier uniquement : on supprime les accents
            normalized = unicodedata.normalize("NFKD", part)
            ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
            # Remplacer espaces par underscores, supprimer chars dangereux
            ascii_name = re.sub(r"[^\w\-\.]", "_", ascii_name)
            ascii_name = re.sub(r"_+", "_", ascii_name)  # double underscores
            sanitized_parts.append(ascii_name)
    return "/".join(sanitized_parts)


def upload_single_file(client, bucket, rel_path, local_path, dry_run=False):
    global uploaded_count, error_count
    try:
        if dry_run:
            with lock:
                uploaded_count += 1
            return "DRY-RUN"

        ext = Path(local_path).suffix.lower()
        content_type_map = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        content_type = content_type_map.get(ext, "application/octet-stream")

        # Sanitize le nom de fichier (supprime accents, espaces)
        safe_key = sanitize_key(rel_path)
        if safe_key != rel_path:
            print(f"[~] Renomme : {rel_path}")
            print(f"         -> {safe_key}")

        with open(local_path, "rb") as f:
            client.put_object(
                Bucket=bucket,
                Key=safe_key,
                Body=f,
                ContentType=content_type,
            )

        with lock:
            uploaded_count += 1
            if uploaded_count % 50 == 0:
                print(f"[>] {uploaded_count} fichiers envoyés...", flush=True)
        return "OK"

    except Exception as e:
        with lock:
            error_count += 1
        print(f"[!] ERREUR {rel_path} : {e}", flush=True)
        return f"ERROR: {e}"


def main():
    if not settings.USE_SUPABASE_STORAGE:
        print("[!] USE_SUPABASE_STORAGE est False dans .env — abandon.")
        return

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dry_run = "--dry-run" in sys.argv
    subfolder_filter = args[0] if args else None

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    search_root = MEDIA_ROOT / subfolder_filter if subfolder_filter else MEDIA_ROOT

    if not search_root.exists():
        print(f"[-] Dossier introuvable : {search_root}")
        return

    print("=" * 55)
    print("  UPLOAD MEDIA -> SUPABASE STORAGE")
    print("=" * 55)
    print(f"  Bucket  : {bucket}")
    print(f"  Dossier : {subfolder_filter or 'Tout media/'}")
    print(f"  Mode    : {'SIMULATION (--dry-run)' if dry_run else 'UPLOAD REEL'}")
    print("=" * 55)

    all_files = []
    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            local_path = Path(root) / file
            rel_path = local_path.relative_to(MEDIA_ROOT).as_posix()
            all_files.append((rel_path, local_path))

    total = len(all_files)
    if total == 0:
        print("[-] Aucun fichier trouvé.")
        return

    print(f"\n  {total} fichier(s) à envoyer\n")

    client = get_s3_client()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(upload_single_file, client, bucket, rel_path, local_path, dry_run): rel_path
            for rel_path, local_path in all_files
        }
        for future in as_completed(futures):
            pass

    print(f"\n{'=' * 55}")
    print(f"  Envoyés  : {uploaded_count}")
    print(f"  Erreurs  : {error_count}")
    print(f"  Total    : {total}")
    if dry_run:
        print("\n  [Simulation — aucun fichier réellement envoyé]")
    print("=" * 55)


if __name__ == "__main__":
    main()

