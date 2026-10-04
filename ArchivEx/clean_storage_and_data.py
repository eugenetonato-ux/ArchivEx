import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from django.core.files.storage import default_storage
from content.models import CloudFile, Summary
from exams.models import Exam

def clean_database_dummy_data():
    print("\n--- 1. NETTOYAGE DE LA BASE DE DONNEES (PostgreSQL Supabase) ---")
    
    # 1. Épreuves fictives
    exam_count = Exam.objects.count()
    Exam.objects.all().delete()
    print(f"[*] {exam_count} épreuve(s) supprimée(s).")

    # 2. Fichiers de la bibliothèque Cloud
    cloud_count = CloudFile.objects.count()
    CloudFile.objects.all().delete()
    print(f"[*] {cloud_count} fichier(s) Cloud supprimé(s).")

    # 3. Résumés / fiches
    summary_count = Summary.objects.count()
    Summary.objects.all().delete()
    print(f"[*] {summary_count} résumé(s) supprimé(s).")

    print("[+] Base de données nettoyée avec succès (vos Utilisateurs, Écoles, Filières et Matières ont été préservés) !")

def clean_supabase_bucket():
    print("\n--- 2. VIDAGE DU BUCKET SUPABASE STORAGE ---")
    if not settings.USE_SUPABASE_STORAGE:
        print("[!] Supabase storage n'est pas activé.")
        return

    import boto3
    s3 = boto3.resource(
        's3',
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME
    )
    bucket = s3.Bucket(settings.AWS_STORAGE_BUCKET_NAME)
    print(f"[*] Suppression de tous les objets dans le bucket '{settings.AWS_STORAGE_BUCKET_NAME}'...")
    bucket.objects.all().delete()
    print("[+] Bucket Supabase Storage entièrement vidé !")

def clean_local_media():
    print("\n--- 3. NETTOYAGE DU DOSSIER MEDIA LOCAL ---")
    media_path = settings.BASE_DIR / "media"
    import shutil
    for item in media_path.iterdir():
        if item.is_dir() and item.name in ["exams", "corrections", "summaries_pdf", "cloud_library"]:
            shutil.rmtree(item)
            item.mkdir(exist_ok=True)
            print(f"[*] Dossier media/{item.name}/ vidé.")
    print("[+] Dossier media/ local nettoyé !")

if __name__ == "__main__":
    confirm = input("Êtes-vous sûr de vouloir supprimer TOUTES les épreuves et TOUS les fichiers du storage ? (tapez 'oui' pour confirmer) : ")
    if confirm.strip().lower() == "oui":
        clean_database_dummy_data()
        clean_supabase_bucket()
        clean_local_media()
        print("\n=== REINITIALISATION COMPLETE REUSSIE : Vous pouvez repartir à zéro ! ===")
    else:
        print("Opération annulée.")
