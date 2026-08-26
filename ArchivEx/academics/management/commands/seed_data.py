import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.conf import settings

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from exams.models import Exam
from accounts.models import StudentProfile

User = get_user_model()


def generate_dummy_pdf_content(title):
    """Génère un contenu binaire de fichier PDF minimaliste et valide."""
    pdf_template = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 75 >>
stream
BT
/F1 18 Tf
50 700 TD
({title} - ArchivEx PDF Demo) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000246 00000 n 
0000000371 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
448
%%EOF
"""
    return pdf_template.encode('utf-8')


class Command(BaseCommand):
    help = "Popule la base de données avec la structure académique, des sujets d'examens et un utilisateur de démonstration."

    def handle(self, *args, **options):
        self.stdout.write("Initialisation des données de test ArchivEx...")

        # 1. Niveaux
        l1, _ = Level.objects.get_or_create(name="L1")
        l2, _ = Level.objects.get_or_create(name="L2")
        l3, _ = Level.objects.get_or_create(name="L3")

        # 2. Écoles
        school, _ = School.objects.get_or_create(
            slug="eneam",
            defaults={
                "name": "ENEAM — École Nationale d'Économie Appliquée et de Management",
                "description": "Grande école supérieure universitaire spécialisée en informatique, gestion et planification.",
                "is_active": True,
            }
        )

        # 3. Année Académique
        year_2025, _ = AcademicYear.objects.get_or_create(label="2025-2026")

        # 4. Filières
        ig_filiere, _ = Filiere.objects.get_or_create(
            school=school,
            level=l1,
            name="Informatique de Gestion (IG)",
            defaults={"description": "Algorithmique, bases de données, génie logiciel et développement d'applications d'entreprise."}
        )

        pgp_filiere, _ = Filiere.objects.get_or_create(
            school=school,
            level=l1,
            name="Planification et Gestion de Projets (PGP)",
            defaults={"description": "Management de projets, économie appliquée et étude d'impact."}
        )

        cf_filiere, _ = Filiere.objects.get_or_create(
            school=school,
            level=l1,
            name="Comptabilité et Finance (CF)",
            defaults={"description": "Comptabilité générale, contrôle de gestion et analyse financière."}
        )

        # 5. Semestres
        s1, _ = Semester.objects.get_or_create(
            filiere=ig_filiere,
            academic_year=year_2025,
            label="Semestre 1"
        )
        s2, _ = Semester.objects.get_or_create(
            filiere=ig_filiere,
            academic_year=year_2025,
            label="Semestre 2"
        )

        # 6. Matières
        algo, _ = Subject.objects.get_or_create(
            semester=s1,
            name="Algorithmique & Algèbre de Boole",
            defaults={"is_free": True}  # Gratuit
        )

        bdd, _ = Subject.objects.get_or_create(
            semester=s1,
            name="Bases de Données RelRelationnelles (SQL)",
            defaults={"is_free": False}  # Premium
        )

        se, _ = Subject.objects.get_or_create(
            semester=s1,
            name="Systèmes d'Exploitation & Architecture",
            defaults={"is_free": False}  # Premium
        )

        web, _ = Subject.objects.get_or_create(
            semester=s2,
            name="Développement Web & HTTP",
            defaults={"is_free": True}
        )

        # 7. Épreuves & PDF de test
        os.makedirs(os.path.join(settings.MEDIA_ROOT, "exams"), exist_ok=True)

        exams_data = [
            {
                "title": "Examen Final — Algorithmique S1",
                "subject": algo,
                "semester": s1,
                "filiere": ig_filiere,
                "level": l1,
                "academic_year": year_2025,
                "exam_type": "examen",
                "year": 2024,
                "description": "Sujet officiel portant sur les structures de données récursives, les arbres binaires et le tri rapide.",
                "is_free": True,
                "is_published": True,
            },
            {
                "title": "Devoir Surveillé — Bases de Données (SQL)",
                "subject": bdd,
                "semester": s1,
                "filiere": ig_filiere,
                "level": l1,
                "academic_year": year_2025,
                "exam_type": "devoir",
                "year": 2024,
                "description": "Devoir pratique de 2h sur la modélisation UML/ER et les requêtes SQL complexes (JOIN, GROUP BY, HAVING).",
                "is_free": False,
                "is_published": True,
            },
            {
                "title": "Session de Rattrapage — Systèmes d'Exploitation",
                "subject": se,
                "semester": s1,
                "filiere": ig_filiere,
                "level": l1,
                "academic_year": year_2025,
                "exam_type": "rattrapage",
                "year": 2023,
                "description": "Sujet de rattrapage sur la gestion des processus, les sémaphores de Djikstra et la mémoire virtuelle.",
                "is_free": False,
                "is_published": True,
            },
            {
                "title": "Travaux Dirigés N°2 — Développement Web",
                "subject": web,
                "semester": s2,
                "filiere": ig_filiere,
                "level": l1,
                "academic_year": year_2025,
                "exam_type": "td",
                "year": 2025,
                "description": "Fiche de TD et corrigé sur l'intégration HTML5/CSS3, JavaScript DOM et formulaires.",
                "is_free": True,
                "is_published": True,
            },
        ]

        for item in exams_data:
            exam, created = Exam.objects.get_or_create(
                title=item["title"],
                defaults=item
            )
            if created or not exam.file:
                pdf_bytes = generate_dummy_pdf_content(exam.title)
                file_name = f"exam_{exam.id}.pdf"
                exam.file.save(file_name, ContentFile(pdf_bytes), save=True)

        # 8. Utilisateur Étudiant de Démonstration
        user_demo, user_created = User.objects.get_or_create(
            username="etudiant@univ.edu",
            defaults={
                "email": "etudiant@univ.edu",
                "first_name": "Jacques",
                "last_name": "Kouassi",
                "is_staff": False,
            }
        )
        if user_created:
            user_demo.set_password("Password123!")
            user_demo.save()
            StudentProfile.objects.create(
                user=user_demo,
                school=school,
                level=l1,
                filiere=ig_filiere
            )

        # Admin user
        admin_user, admin_created = User.objects.get_or_create(
            username="admin@archivex.univ",
            defaults={
                "email": "admin@archivex.univ",
                "first_name": "Admin",
                "last_name": "System",
                "is_staff": True,
                "is_superuser": True
            }
        )
        if admin_created:
            admin_user.set_password("AdminPass123!")
            admin_user.save()

        self.stdout.write(self.style.SUCCESS("[OK] Donnees de demonstration ArchivEx generees avec succes !"))
        self.stdout.write(self.style.SUCCESS("  - Compte Etudiant : etudiant@univ.edu / Password123!"))
        self.stdout.write(self.style.SUCCESS("  - Compte Administrateur : admin@archivex.univ / AdminPass123!"))

