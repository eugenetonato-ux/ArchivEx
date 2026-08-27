from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from contributors.models import ContributorProfile
from contributors.permissions import check_school_permission, require_school_permission
from django.http import HttpResponse

User = get_user_model()


class ContributorSchoolSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school_eneam = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_flash = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)

        self.contrib_eneam = User.objects.create_user(username="contrib_eneam", password="Password123!")
        self.prof_eneam = ContributorProfile.objects.create(
            user=self.contrib_eneam,
            role="SCHOOL_CONTENT_MANAGER",
            is_active=True
        )
        self.prof_eneam.assigned_schools.add(self.school_eneam)

        self.superadmin = User.objects.create_superuser(username="superadmin", email="admin@test.com", password="Password123!")

    def test_school_manager_permissions(self):
        """School manager can manage assigned school, but not unauthorized school."""
        self.assertTrue(check_school_permission(self.contrib_eneam, self.school_eneam))
        self.assertFalse(check_school_permission(self.contrib_eneam, self.school_flash))

    def test_superadmin_permissions(self):
        """Superadmin has unrestricted access to all schools."""
        self.assertTrue(check_school_permission(self.superadmin, self.school_eneam))
        self.assertTrue(check_school_permission(self.superadmin, self.school_flash))

    def test_server_side_decorator_http_403_enforcement(self):
        """Decorator raises PermissionDenied (403) when attempting unauthorized access."""
        @require_school_permission(school_id_param="school_id")
        def mock_view(request, school_id):
            return HttpResponse("Success")

        class MockRequest:
            def __init__(self, user):
                self.user = user
                self.GET = {}
                self.POST = {}

        # Allowed request
        req_allowed = MockRequest(self.contrib_eneam)
        res = mock_view(req_allowed, school_id=self.school_eneam.id)
        self.assertEqual(res.status_code, 200)

        # Tampered request -> HTTP 403 expected
        from django.core.exceptions import PermissionDenied
        req_tampered = MockRequest(self.contrib_eneam)
        with self.assertRaises(PermissionDenied):
            mock_view(req_tampered, school_id=self.school_flash.id)


class Phase11AdministrationTests(TestCase):
    """Suite de tests automatisés pour le Portail d'Administration Privé (/administration/)."""

    def setUp(self):
        self.client = Client()

        # Academic structure
        self.school_eneam = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_flash = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)
        self.level = Level.objects.create(name="Licence 1", code="L1")
        self.filiere = Filiere.objects.create(school=self.school_eneam, level=self.level, name="Informatique")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")
        self.subject = Subject.objects.create(semester=self.semester, name="Algorithmique")

        # Users
        self.student = User.objects.create_user(username="normal_student", password="Password123!")

        self.contrib_eneam = User.objects.create_user(username="staff_eneam", password="Password123!", is_staff=True)
        self.prof_eneam = ContributorProfile.objects.create(
            user=self.contrib_eneam,
            role="SCHOOL_CONTENT_MANAGER",
            is_active=True
        )
        self.prof_eneam.assigned_schools.add(self.school_eneam)

        self.superadmin = User.objects.create_superuser(username="admin_boss", password="Password123!")

    def test_unauthenticated_access_redirects_to_login(self):
        """Unauthenticated access to /administration/ redirects to /administration/login/."""
        res = self.client.get(reverse("contributors:admin_dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("contributors:admin_login"), res.url)

    def test_admin_login_flow(self):
        """Staff members can log in using /administration/login/."""
        res = self.client.get(reverse("contributors:admin_login"))
        self.assertEqual(res.status_code, 200)

        # Login post
        res_post = self.client.post(reverse("contributors:admin_login"), {
            "username": "staff_eneam",
            "password": "Password123!"
        })
        self.assertEqual(res_post.status_code, 302)
        self.assertEqual(res_post.url, "/administration/")

    def test_authorized_staff_can_access_administration(self):
        """Authorized staff/contributors access /administration/ with status 200 OK."""
        self.client.login(username="staff_eneam", password="Password123!")
        res = self.client.get(reverse("contributors:admin_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Administration")
        self.assertContains(res, "ENEAM")

    def test_active_university_context_session_persistence(self):
        """Active university context is set in session and displayed across administration pages."""
        self.client.login(username="admin_boss", password="Password123!")
        res = self.client.get(reverse("contributors:set_context") + f"?school_id={self.school_eneam.id}")
        self.assertEqual(res.status_code, 302)

        res_dash = self.client.get(reverse("contributors:admin_dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "ENEAM")

    def test_exam_creation_workflow(self):
        """Authorized contributor can create and publish an exam using free-text subject input."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        dummy_pdf = SimpleUploadedFile("test.pdf", b"%PDF-1.4 test content", content_type="application/pdf")

        self.client.login(username="admin_boss", password="Password123!")

        # Set active context first
        self.client.get(reverse("contributors:set_context") + f"?school_id={self.school_eneam.id}&filiere_id={self.filiere.id}&semester_id={self.semester.id}")

        exam_data = {
            "title": "Épreuve d'Algorithmique L1",
            "subject_name": "Algorithmique Avancée",
            "year": "2026",
            "exam_type": "examen",
            "is_free": "False",
            "is_published": "True",
            "description": "Remarques",
            "file": dummy_pdf,
        }
        res = self.client.post(reverse("contributors:exam_create"), data=exam_data)
        self.assertEqual(res.status_code, 302)

        from exams.models import Exam
        exam = Exam.objects.filter(title="Épreuve d'Algorithmique L1").first()
        self.assertIsNotNone(exam)
        self.assertTrue(exam.is_published)
        self.assertFalse(exam.is_free)
        self.assertEqual(exam.filiere, self.filiere)
        self.assertEqual(exam.subject.name, "Algorithmique Avancée")

    def test_free_text_subject_creation_and_context_inheritance(self):
        """Creating an exam with a new subject name automatically creates the Subject in the active semester context."""
        self.client.login(username="admin_boss", password="Password123!")
        self.client.get(reverse("contributors:set_context") + f"?school_id={self.school_eneam.id}&filiere_id={self.filiere.id}&semester_id={self.semester.id}")

        exam_data = {
            "title": "Épreuve de Physique 2026",
            "subject_name": "Physique Quantique 2026",
            "year": "2026",
            "exam_type": "examen",
            "is_free": "True",
            "is_published": "True",
        }
        res = self.client.post(reverse("contributors:exam_create"), data=exam_data)
        self.assertEqual(res.status_code, 302)

        subject = Subject.objects.filter(name="Physique Quantique 2026", semester=self.semester).first()
        self.assertIsNotNone(subject)

        # Submit another exam with same subject name (case-insensitive) -> should reuse same Subject
        exam_data_2 = {
            "title": "Épreuve de Physique Rattrapage",
            "subject_name": "physique quantique 2026",
            "year": "2026",
            "exam_type": "rattrapage",
            "is_free": "True",
            "is_published": "True",
        }
        res2 = self.client.post(reverse("contributors:exam_create"), data=exam_data_2)
        self.assertEqual(res2.status_code, 302)
        self.assertEqual(Subject.objects.filter(name__iexact="physique quantique 2026").count(), 1)

    def test_summary_creation_workflow(self):
        """Authorized contributor can create a summary of course."""
        self.client.login(username="admin_boss", password="Password123!")
        summary_data = {
            "title": "Fiche de synthèse Algorithmique",
            "subject": self.subject.id,
            "introduction": "Intro",
            "content": "Contenu complet rédigé",
            "access_type": "PREMIUM",
            "publication_status": "PUBLISHED",
        }
        res = self.client.post(reverse("contributors:summary_create"), data=summary_data)
        self.assertEqual(res.status_code, 302)

        from content.models import Summary
        sm = Summary.objects.filter(title="Fiche de synthèse Algorithmique").first()
        self.assertIsNotNone(sm)
        self.assertEqual(sm.publication_status, "PUBLISHED")

    def test_guide_creation_workflow(self):
        """Authorized contributor can create a methodological guide."""
        self.client.login(username="admin_boss", password="Password123!")
        guide_data = {
            "title": "Guide de révision Algorithmique",
            "subject": self.subject.id,
            "introduction": "Intro du guide",
            "objectives": "Objectifs",
            "how_to_study": "Méthode",
            "key_concepts": "Notions",
            "access_type": "FREE",
            "publication_status": "PUBLISHED",
        }
        res = self.client.post(reverse("contributors:guide_create"), data=guide_data)
        self.assertEqual(res.status_code, 302)

        from content.models import Guide
        gd = Guide.objects.filter(title="Guide de révision Algorithmique").first()
        self.assertIsNotNone(gd)

    def test_article_creation_workflow(self):
        """Authorized contributor can write an advice article."""
        self.client.login(username="admin_boss", password="Password123!")
        article_data = {
            "title": "Comment réussir la Licence 1",
            "category": "METHODOLOGY",
            "summary": "Résumé de l'article",
            "content": "Contenu détaillé de l'article",
            "publication_status": "PUBLISHED",
        }
        res = self.client.post(reverse("contributors:article_create"), data=article_data)
        self.assertEqual(res.status_code, 302)

        from content.models import Article
        art = Article.objects.filter(title="Comment réussir la Licence 1").first()
        self.assertIsNotNone(art)

    def test_exam_status_toggle(self):
        """Toggling publication status of an exam switches between published and draft."""
        from exams.models import Exam
        exam = Exam.objects.create(
            title="Épreuve Test Toggle",
            subject=self.subject,
            filiere=self.filiere,
            level=self.level,
            academic_year=self.year,
            semester=self.semester,
            year="2026",
            exam_type="EXAM",
            is_published=True
        )
        self.client.login(username="admin_boss", password="Password123!")
        res = self.client.post(reverse("contributors:exam_toggle_status", kwargs={"pk": exam.pk}))
        self.assertEqual(res.status_code, 302)

        exam.refresh_from_db()
        self.assertFalse(exam.is_published)

    def test_django_admin_remains_independent_at_django_admin(self):
        """Django admin interface at /django-admin/ remains completely functional and independent."""
        res = self.client.get("/django-admin/login/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Django")

    def test_zero_emoji_policy_in_administration_portal(self):
        """Verify zero Unicode emojis appear in custom administration templates."""
        emojis = ["📚", "📄", "🎯", "💡", "🔒", "⚡", "✓", "⭐", "🚀", "👋", "❤️", "🔔"]
        self.client.login(username="admin_boss", password="Password123!")
        for route_name in [
            "contributors:admin_dashboard",
            "contributors:exam_list",
            "contributors:summary_list",
            "contributors:guide_list",
            "contributors:article_list",
            "contributors:subject_list",
            "contributors:structure_overview",
        ]:
            res = self.client.get(reverse(route_name))
            content = res.content.decode("utf-8")
            for emoji in emojis:
                self.assertNotIn(emoji, content, f"Emoji {emoji} found in response for {route_name}")

