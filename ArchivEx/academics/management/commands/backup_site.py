import os
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.conf import settings
from django.utils import timezone


class Command(BaseCommand):
    help = "Genere une archive ZIP complete de sauvegarde (Base de donnees + Fichiers Medias PDF/Images) prete a etre exportee."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            type=str,
            default=str(settings.BASE_DIR / "backups"),
            help="Repertoire de destination pour stocker l'archive de sauvegarde.",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Sauvegarder uniquement la base de donnees sans le dossier media.",
        )

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        no_media = options["no_media"]
        output_dir.mkdir(parents=True, exist_ok=True)

        now = timezone.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        zip_filename = f"archivex_backup_{timestamp}.zip"
        zip_path = output_dir / zip_filename

        scratch_dir = settings.BASE_DIR / f"_temp_backup_{timestamp}"
        scratch_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write(self.style.MIGRATE_HEADING("[+] Debut de la sauvegarde ArchivEx..."))

        try:
            # 1. Export des donnees de la base de donnees en JSON
            self.stdout.write("  -> Exportation de la base de donnees (JSON)...")
            json_dump_path = scratch_dir / "database_dump.json"
            try:
                call_command(
                    "dumpdata",
                    exclude=["contenttypes", "auth.Permission", "sessions.Session"],
                    indent=2,
                    output=str(json_dump_path),
                )
                self.stdout.write(self.style.SUCCESS("  [OK] Base de donnees exportee (database_dump.json)"))
            except Exception as e:
                raise CommandError(f"Erreur lors de l'export de la base de donnees: {e}")

            # Statistiques médias
            media_count = 0
            media_total_bytes = 0

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # A. Ajouter le dump JSON
                zipf.write(json_dump_path, arcname="database_dump.json")

                # B. Si SQLite existe, ajouter aussi le fichier brut db.sqlite3
                sqlite_path = settings.BASE_DIR / "db.sqlite3"
                if sqlite_path.exists():
                    zipf.write(sqlite_path, arcname="db.sqlite3")
                    self.stdout.write(self.style.SUCCESS("  [OK] Fichier SQLite physique inclus (db.sqlite3)"))

                # C. Ajouter les fichiers medias (PDFs des epreuves, corriges, resumes, avatars)
                if not no_media and settings.MEDIA_ROOT:
                    media_root = Path(settings.MEDIA_ROOT)
                    if media_root.exists():
                        self.stdout.write("  -> Archivage des fichiers medias (PDFs, epreuves, resumes)...")
                        for root, _, files in os.walk(media_root):
                            for file in files:
                                file_path = Path(root) / file
                                if file.startswith(".") or file.endswith(".tmp"):
                                    continue
                                rel_path = file_path.relative_to(media_root)
                                zipf.write(file_path, arcname=f"media/{rel_path.as_posix()}")
                                media_count += 1
                                media_total_bytes += file_path.stat().st_size
                        self.stdout.write(self.style.SUCCESS(f"  [OK] {media_count} fichiers medias archives ({media_total_bytes / (1024*1024):.2f} Mo)"))
                    else:
                        self.stdout.write(self.style.WARNING("  [WARN] Dossier MEDIA_ROOT introuvable, medias ignores."))

                # D. Manifeste d'informations de sauvegarde
                manifest = {
                    "platform": "ArchivEx",
                    "backup_date": now.isoformat(),
                    "timestamp": timestamp,
                    "media_files_count": media_count,
                    "media_total_bytes": media_total_bytes,
                    "includes_media": not no_media,
                }
                zipf.writestr("manifest.json", json.dumps(manifest, indent=2))

            # Resume final
            zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.SUCCESS("Sauvegarde terminee avec succes !"))
            self.stdout.write(f"Fichier : {zip_path.resolve()}")
            self.stdout.write(f"Taille  : {zip_size_mb:.2f} Mo")
            self.stdout.write(f"Medias  : {media_count} fichiers inclus")
            self.stdout.write("=" * 60)
            self.stdout.write(
                self.style.NOTICE(
                    "\nConseil : Telechargez ce fichier ZIP depuis l'onglet 'Files' de PythonAnywhere "
                    "et conservez-le sur votre ordinateur ou Google Drive."
                )
            )

        finally:
            if scratch_dir.exists():
                shutil.rmtree(scratch_dir)
