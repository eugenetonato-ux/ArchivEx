from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from accounts.models import StudentProfile
from exams.models import Exam
from contributors.models import ContributorProfile

User = get_user_model()


class MultiSchoolIsolationTest(TestCase):
    def setUp(self):
        # 1. Université A : ENEAM avec épreuves
        self.school_a = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.level_a = Level.objects.create(name="Licence 1", code="L1", school=self.school_a)
        self.filiere_a = Filiere.objects.create(school=self.school_a, level=self.level_a, name="Informatique de Gestion", code="IG")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester_a = Semester.objects.create(filiere=self.filiere_a, academic_year=self.year, label="Semestre 1", number=1)
        self.subject_a = Subject.objects.create(semester=self.semester_a, name="Algorithmique", code="UE-ALGO")

        self.exam_a = Exam.objects.create(
            title="Examen Algorithmique 2025 ENEAM",
            subject=self.subject_a,
            semester=self.semester_a,
            filiere=self.filiere_a,
            level=self.level_a,
            academic_year=self.year,
            exam_type="examen",
            year=2025,
            file="exams/algo_eneam.pdf",
            is_published=True,
            is_free=True,
        )

        # 2. Université B : FASEG sans épreuves pour l'instant
        self.school_b = School.objects.create(name="FASEG", code="FASEG", slug="faseg", is_active=True)
        self.level_b = Level.objects.create(name="Licence 1", code="L1", school=self.school_b)
        self.filiere_b = Filiere.objects.create(school=self.school_b, level=self.level_b, name="Sciences Économiques", code="SE")
        self.semester_b = Semester.objects.create(filiere=self.filiere_b, academic_year=self.year, label="Semestre 1", number=1)
        self.subject_b = Subject.objects.create(semester=self.semester_b, name="Macroéconomie", code="UE-MACRO")

        # 3. Étudiant inscrit à la FASEG
        self.student_faseg = User.objects.create_user(
            username="etudiant.faseg@univ.edu",
            email="etudiant.faseg@univ.edu",
            password="Password123!"
        )
        self.profile_faseg = StudentProfile.objects.create(
            user=self.student_faseg,
            school=self.school_b,
            level=self.level_b,
            filiere=self.filiere_b
        )

        # 4. Contributeur / Admin rattaché aux deux écoles
        self.admin_user = User.objects.create_superuser(
            username="admin.multischool@univ.edu",
            email="admin.multischool@univ.edu",
            password="Password123!"
        )
        self.admin_profile = ContributorProfile.objects.create(
            user=self.admin_user,
            role="SUPER_ADMIN"
        )
        self.admin_profile.assigned_schools.add(self.school_a, self.school_b)

    def test_student_from_faseg_only_sees_faseg_on_resources_page(self):
        """
        Un étudiant inscrit à la FASEG ne doit jamais voir les épreuves de l'ENEAM.
        Comme la FASEG n'a pas encore d'épreuve, la page affiche un état vide pour la FASEG.
        """
        client = Client()
        client.login(username="etudiant.faseg@univ.edu", password="Password123!")

        res = client.get(reverse("exams:liste"))
        self.assertEqual(res.status_code, 200)

        # L'école active doit être strictement la FASEG
        self.assertEqual(res.context["current_school"], self.school_b)
        # Aucune épreuve dans les résultats (pas de fuite d'ENEAM)
        self.assertEqual(len(res.context["exams"]), 0)
        self.assertEqual(res.context["total_resources_count"], 0)
        self.assertNotContains(res, "Examen Algorithmique 2025 ENEAM")
        self.assertContains(res, "FASEG")

    def test_student_from_faseg_dashboard_is_completely_isolated(self):
        """
        Le tableau de bord d'un étudiant FASEG sans épreuve ne retombe pas sur l'ENEAM.
        Il affiche 0 épreuve pour son université.
        """
        client = Client()
        client.login(username="etudiant.faseg@univ.edu", password="Password123!")

        res = client.get(reverse("accounts:dashboard"))
        self.assertEqual(res.status_code, 200)

        self.assertEqual(res.context["semester_exams_count"], 0)
        self.assertEqual(len(res.context["recent_exams"]), 0)
        self.assertNotContains(res, "Algorithmique")
        self.assertNotContains(res, "ENEAM")

    def test_admin_switch_school_to_faseg_and_lands_on_faseg_public_site(self):
        """
        Quand un administrateur sélectionne la FASEG dans l'administration
        et bascule vers le site public, il atterrit sur le site public de la FASEG.
        """
        client = Client()
        client.login(username="admin.multischool@univ.edu", password="Password123!")

        # 1. Sélectionne FASEG dans l'administration
        switch_res = client.get(reverse("contributors:set_context") + f"?school_id={self.school_b.id}")
        self.assertEqual(switch_res.status_code, 302)

        # 2. Bascule vers le site public (accueil)
        home_res = client.get(reverse("academics:home"))
        self.assertEqual(home_res.status_code, 200)
        self.assertEqual(home_res.context["current_school"], self.school_b)

        # 3. Consulte les ressources publiques : FASEG est actif, pas d'épreuve d'ENEAM
        resources_res = client.get(reverse("exams:liste"))
        self.assertEqual(resources_res.status_code, 200)
        self.assertEqual(resources_res.context["current_school"], self.school_b)
        self.assertEqual(len(resources_res.context["exams"]), 0)
        self.assertNotContains(resources_res, "Examen Algorithmique 2025 ENEAM")

    def test_visitor_can_change_public_school(self):
        """
        Un visiteur public non connecté peut changer d'université active
        via la route dédiée et ses choix sont conservés en session.
        """
        client = Client()

        # Choix de la FASEG
        res_change = client.get(reverse("academics:change_school", kwargs={"school_id": self.school_b.id}))
        self.assertEqual(res_change.status_code, 302)

        # Consultation des épreuves
        res_exams = client.get(reverse("exams:liste"))
        self.assertEqual(res_exams.status_code, 200)
        self.assertEqual(res_exams.context["current_school"], self.school_b)
        self.assertEqual(len(res_exams.context["exams"]), 0)

        # Choix de l'ENEAM
        client.get(reverse("academics:change_school", kwargs={"school_id": self.school_a.id}))
        res_eneam = client.get(reverse("exams:liste"))
        self.assertEqual(res_eneam.context["current_school"], self.school_a)
        self.assertEqual(len(res_eneam.context["exams"]), 1)
        self.assertContains(res_eneam, "Examen Algorithmique 2025 ENEAM")

    def test_global_search_is_isolated_to_school(self):
        """
        La recherche globale pour un étudiant FASEG ne retourne pas les résultats d'ENEAM.
        """
        client = Client()
        client.login(username="etudiant.faseg@univ.edu", password="Password123!")

        res = client.get(reverse("academics:global_search") + "?q=Algorithmique")
        self.assertEqual(res.status_code, 200)
        # Ne doit pas trouver l'épreuve d'Algorithmique d'ENEAM
        self.assertEqual(len(res.context["exams_results"]), 0)
        self.assertEqual(len(res.context["subjects_results"]), 0)
