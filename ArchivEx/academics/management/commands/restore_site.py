import os
import shutil
import zipfile
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.conf import settings


class Command(BaseCommand):
    help = "Restaure le site ArchivEx a partir d'un fichier ZIP genere par backup_site."

    def add_arguments(self, parser):
        parser.add_argument(
            "zip_file",
            type=str,
            help="Chemin vers le fichier ZIP de sauvegarde a restaurer.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Executer sans demander de confirmation.",
        )

    def handle(self, *args, **options):
        zip_path = Path(options["zip_file"])
        if not zip_path.exists():
            raise CommandError(f"Le fichier de sauvegarde '{zip_path}' n'existe pas.")

        if not zipfile.is_zipfile(zip_path):
            raise CommandError(f"Le fichier '{zip_path}' n'est pas une archive ZIP valide.")

        self.stdout.write(self.style.MIGRATE_HEADING(f"[+] Debut de la restauration ArchivEx depuis {zip_path.name}..."))

        if not options["no_input"]:
            confirm = input("ATTENTION : Cette action va remplacer les donnees et medias actuels. Continuer ? (oui/non) : ").strip().lower()
            if confirm not in ["oui", "y", "yes", "o"]:
                self.stdout.write(self.style.WARNING("Restauration annulee par l'utilisateur."))
                return

        temp_dir = settings.BASE_DIR / "scratch_restore"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(temp_dir)

            # 1. Verification du manifeste
            manifest_file = temp_dir / "manifest.json"
            if manifest_file.exists():
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                self.stdout.write(f"  -> Sauvegarde datant du : {manifest.get('backup_date')}")

            # 2. Restauration de la Base de donnees
            json_dump = temp_dir / "database_dump.json"
            sqlite_dump = temp_dir / "db.sqlite3"

            # Si SQLite et que le fichier physique est present :
            db_engine = getattr(settings, "DATABASES", {}).get("default", {}).get("ENGINE", "")
            if "sqlite3" in db_engine and sqlite_dump.exists():
                self.stdout.write("  -> Restauration du fichier SQLite...")
                target_sqlite = settings.BASE_DIR / "db.sqlite3"
                shutil.copy2(sqlite_dump, target_sqlite)
                self.stdout.write(self.style.SUCCESS("  [OK] Fichier db.sqlite3 restaure."))
            elif json_dump.exists():
                self.stdout.write("  -> Application des migrations et chargement du dump JSON...")
                call_command("migrate", interactive=False)
                call_command("loaddata", str(json_dump))
                self.stdout.write(self.style.SUCCESS("  [OK] Donnees chargees avec succes."))
            else:
                self.stdout.write(self.style.WARNING("  [WARN] Aucun fichier de donnees (JSON ou SQLite) trouve dans l'archive."))

            # 3. Restauration des fichiers Medias (PDFs, Images)
            media_extracted = temp_dir / "media"
            if media_extracted.exists():
                self.stdout.write("  -> Restauration des fichiers medias...")
                media_root = Path(settings.MEDIA_ROOT)
                media_root.mkdir(parents=True, exist_ok=True)
                restored_media_count = 0
                for root, _, files in os.walk(media_extracted):
                    for file in files:
                        src = Path(root) / file
                        rel = src.relative_to(media_extracted)
                        dest = media_root / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
                        restored_media_count += 1
                self.stdout.write(self.style.SUCCESS(f"  [OK] {restored_media_count} fichiers medias restaures dans {media_root}"))

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.SUCCESS("Restauration terminee avec succes ! Le site est a jour."))
            self.stdout.write("=" * 60)

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
