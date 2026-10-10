import logging
from django.core.management.base import BaseCommand, CommandError
from academics.models import Filiere, Semester, Subject
from exams.models import Exam

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Duplique les UE (matières) et optionnellement les épreuves d'une filière source vers une filière cible."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default="PLAN",
            help="Code ou nom de la filière source (ex: PLAN). Par défaut: PLAN",
        )
        parser.add_argument(
            "--target",
            type=str,
            default="STAT",
            help="Code ou nom de la filière cible (ex: STAT). Par défaut: STAT",
        )
        parser.add_argument(
            "--with-exams",
            action="store_true",
            help="Duplique également toutes les épreuves associées (PDF, corrigés, résumés).",
        )
        parser.add_argument(
            "--clean-target",
            action="store_true",
            help="Supprime les matières existantes de la filière cible avant duplication.",
        )

    def handle(self, *args, **options):
        source_code = options["source"].strip()
        target_code = options["target"].strip()
        with_exams = options["with_exams"]
        clean_target = options["clean_target"]

        # 1. Recherche de la filière source
        source_filiere = Filiere.objects.filter(code__iexact=source_code).first()
        if not source_filiere:
            source_filiere = Filiere.objects.filter(name__icontains=source_code).first()
        if not source_filiere:
            raise CommandError(f"Filière source introuvable pour '{source_code}'.")

        # 2. Recherche de la filière cible
        target_filiere = Filiere.objects.filter(code__iexact=target_code).first()
        if not target_filiere:
            target_filiere = Filiere.objects.filter(name__icontains=target_code).first()
        if not target_filiere:
            raise CommandError(f"Filière cible introuvable pour '{target_code}'.")

        if source_filiere.id == target_filiere.id:
            raise CommandError("La filière source et la filière cible ne peuvent pas être identiques.")

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n=== DUPLICATION DE FILIÈRE : {source_filiere.name} ({source_filiere.code}) -> {target_filiere.name} ({target_filiere.code}) ==="
            )
        )

        if clean_target:
            self.stdout.write(self.style.WARNING("Nettoyage des matières existantes dans la filière cible..."))
            target_subjects = Subject.objects.filter(semester__filiere=target_filiere)
            Exam.objects.filter(filiere=target_filiere).delete()
            count_deleted = target_subjects.count()
            target_subjects.delete()
            self.stdout.write(self.style.SUCCESS(f"{count_deleted} matière(s) supprimée(s) dans la cible."))

        total_subjects_created = 0
        total_exams_created = 0

        source_semesters = source_filiere.semesters.all().order_by("number")
        if not source_semesters.exists():
            self.stdout.write(self.style.WARNING(f"Aucun semestre trouvé pour la filière source {source_filiere}."))
            return

        for src_sem in source_semesters:
            # Recherche ou création du semestre correspondant dans la filière cible
            target_sem = target_filiere.semesters.filter(number=src_sem.number).first()
            if not target_sem:
                target_sem = Semester.objects.create(
                    filiere=target_filiere,
                    number=src_sem.number,
                    label=src_sem.label,
                    academic_year=src_sem.academic_year,
                    is_active=src_sem.is_active,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Semestre {target_sem.label} (n°{target_sem.number}) créé pour {target_filiere.code}.")
                )
            else:
                if src_sem.academic_year and not target_sem.academic_year:
                    target_sem.academic_year = src_sem.academic_year
                    target_sem.save(update_fields=["academic_year"])

            self.stdout.write(
                f"\n--- Traitement Semestre {src_sem.number} ({src_sem.label}) -> Cible: {target_sem.label} ---"
            )

            for src_subject in src_sem.subjects.all():
                # Vérifier si la matière existe déjà dans le semestre cible
                existing_subject = target_sem.subjects.filter(name__iexact=src_subject.name).first()
                if existing_subject:
                    target_subject = existing_subject
                    # Mettre à jour l'image ou le code si la source a été enrichie
                    fields_to_update = []
                    if src_subject.image and str(target_subject.image) != str(src_subject.image):
                        target_subject.image = src_subject.image.name
                        fields_to_update.append("image")
                    if src_subject.code and target_subject.code != src_subject.code:
                        target_subject.code = src_subject.code
                        fields_to_update.append("code")
                    if fields_to_update:
                        target_subject.save(update_fields=fields_to_update)
                        self.stdout.write(self.style.SUCCESS(f"  [SYNCHRONISEE] UE: {src_subject.name} (champs: {', '.join(fields_to_update)})"))
                    else:
                        self.stdout.write(f"  [EXISTE DEJA] UE: {src_subject.name}")
                else:
                    target_subject = Subject.objects.create(
                        semester=target_sem,
                        name=src_subject.name,
                        code=src_subject.code,
                        description=src_subject.description,
                        image=src_subject.image.name if src_subject.image else "",
                        is_free=src_subject.is_free,
                        is_free_correction=src_subject.is_free_correction,
                        is_active=src_subject.is_active,
                    )
                    total_subjects_created += 1
                    self.stdout.write(self.style.SUCCESS(f"  [CREEE] UE: {target_subject.name} (Code: {target_subject.code})"))

                # Duplication des épreuves si demandé
                if with_exams:
                    src_exams = src_subject.exams.all()
                    for src_exam in src_exams:
                        # Vérifier doublon
                        exam_exists = Exam.objects.filter(
                            filiere=target_filiere,
                            semester=target_sem,
                            subject=target_subject,
                            year=src_exam.year,
                            exam_type=src_exam.exam_type,
                            title=src_exam.title,
                        ).exists()

                        if not exam_exists:
                            Exam.objects.create(
                                title=src_exam.title,
                                subject=target_subject,
                                semester=target_sem,
                                filiere=target_filiere,
                                level=src_exam.level,
                                academic_year=src_exam.academic_year,
                                exam_type=src_exam.exam_type,
                                year=src_exam.year,
                                description=src_exam.description,
                                file=src_exam.file.name if src_exam.file else "",
                                correction_file=src_exam.correction_file.name if src_exam.correction_file else None,
                                summary_file=src_exam.summary_file.name if src_exam.summary_file else None,
                                summary=src_exam.summary,
                                cloud_file=src_exam.cloud_file,
                                cloud_correction_file=src_exam.cloud_correction_file,
                                cloud_summary_file=src_exam.cloud_summary_file,
                                is_free=src_exam.is_free,
                                is_free_correction=src_exam.is_free_correction,
                                is_published=src_exam.is_published,
                                views_count=0,
                                downloads_count=0,
                            )
                            total_exams_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== SYNCHRONISATION TERMINÉE ===\n"
                f"- Matières créées : {total_subjects_created}\n"
                f"- Épreuves créées : {total_exams_created}\n"
                f"Filière cible : {target_filiere.name} ({target_filiere.code})"
            )
        )
