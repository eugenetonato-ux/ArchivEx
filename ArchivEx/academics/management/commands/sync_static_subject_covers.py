import os
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings
from academics.models import Subject


class Command(BaseCommand):
    help = "Copie les images de couverture depuis static/images/ vers media/subjects/ et les assigne automatiquement aux UE correspondantes."

    MAPPING = [
        ("analyse mathématique.png", "analyse_mathematique.png", ["analyse math"]),
        ("CIVE.png", "cive.png", ["cive"]),
        ("compta financière.png", "compta_financiere.png", ["comptabilit", "financi"]),
        ("entrepreneuriat.png", "entrepreneuriat.png", ["entrepreneuriat"]),
        ("management de la qualité.png", "management_qualite.png", ["qualit"]),
        ("HPE.png", "histoire_pensee_eco.png", ["histoire"]),
        ("droit.png", "droit.png", ["droit"]),
        ("Microéconomie.png", "microeconomie.png", ["micro"]),
        ("Sociologie des organisations.png", "sociologie_organisations.png", ["sociologie"]),
        ("Statistique descriptive.png", "statistique_descriptive.png", ["statistique"]),
        ("algèbre.png", "algebre_lineaire.png", ["alg"]),
        ("compta nationale.png", "compta_nationale.png", ["nationale"]),
        ("dev personnel.png", "dev_personnel.png", ["personnel"]),
        ("informatique.png", "informatique.png", ["informatique"]),
        ("introplan.png", "intro_planification.png", ["planification"]),
        ("macro.png", "macroeconomie.png", ["macro"]),
        ("Probabilité.png", "probabilites.png", ["probabilit"]),
    ]

    def handle(self, *args, **options):
        static_dir = os.path.join(settings.BASE_DIR, "static", "images")
        media_subjects_dir = os.path.join(settings.MEDIA_ROOT, "subjects")
        os.makedirs(media_subjects_dir, exist_ok=True)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== SYNCHRONISATION DES PHOTOS DE COUVERTURE D'UE ==="))
        self.stdout.write(f"Source : {static_dir}")
        self.stdout.write(f"Destination : {media_subjects_dir}\n")

        synced_count = 0
        assigned_subjects_count = 0

        for src_name, dest_name, keywords in self.MAPPING:
            src_path = os.path.join(static_dir, src_name)
            dest_path = os.path.join(media_subjects_dir, dest_name)

            if not os.path.exists(src_path):
                self.stdout.write(self.style.WARNING(f"[ABSENT] Fichier source introuvable: {src_name}"))
                continue

            # 1. Copie vers media/subjects/ avec nom normalisé
            shutil.copy2(src_path, dest_path)
            synced_count += 1
            rel_media_path = f"subjects/{dest_name}"

            # 2. Recherche et association aux matières
            matching_subjects = []
            for s in Subject.objects.all():
                s_name = s.name.lower()
                # Doit correspondre à tous les mots-clés de la liste
                if all(kw in s_name for kw in keywords):
                    matching_subjects.append(s)

            for s in matching_subjects:
                s.image = rel_media_path
                s.save(update_fields=["image"])
                assigned_subjects_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [OK] {s.name} ({s.semester.filiere.code} - {s.semester.label}) -> {rel_media_path}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== OPERATION TERMINEE AVEC SUCCES ===\n"
                f"- Fichiers synchronisés : {synced_count}/17\n"
                f"- Matières mises à jour en base de données : {assigned_subjects_count}\n"
            )
        )
