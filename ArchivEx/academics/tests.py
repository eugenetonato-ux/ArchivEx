from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from accounts.models import StudentProfile
from exams.models import Exam
from content.models import Summary, Guide, Article

User = get_user_model()


class GlobalSearchSystemTest(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Academic hierarchy
        self.school_eneam = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_flash = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)
        self.level = Level.objects.create(name="Licence 1", code="L1")
        self.filiere_eneam = Filiere.objects.create(school=self.school_eneam, level=self.level, name="Planification")
        self.filiere_flash = Filiere.objects.create(school=self.school_flash, level=self.level, name="Lettres")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere_eneam, academic_year=self.year, label="Semestre 1")
        
        # Test Data
        self.subject = Subject.objects.create(semester=self.semester, name="Probabilités & Statistique")
        
        self.exam_published = Exam.objects.create(
            title="Examen Probabilités 2025",
            subject=self.subject,
            filiere=self.filiere_eneam,
            level=self.level,
            academic_year=self.year,
            semester=self.semester,
            year="2025",
            exam_type="EXAM",
            is_published=True,
            is_free=True
        )

        self.exam_draft = Exam.objects.create(
            title="Brouillon Probabilités Secret",
            subject=self.subject,
            filiere=self.filiere_eneam,
            level=self.level,
            academic_year=self.year,
            semester=self.semester,
            year="2025",
            exam_type="EXAM",
            is_published=False
        )

        self.summary_published = Summary.objects.create(
            title="Fiche Résumé Probabilités",
            subject=self.subject,
            content="Contenu résumé probabilités...",
            publication_status="PUBLISHED",
            access_type="FREE"
        )

        self.guide_published = Guide.objects.create(
            title="Guide de Préparation Probabilités",
            subject=self.subject,
            introduction="Intro guide probabilités...",
            publication_status="PUBLISHED"
        )

        self.article_published = Article.objects.create(
            title="Conseils pour Réussir en Probabilités",
            summary="Extrait de conseils...",
            content="Contenu complet conseils...",
            publication_status="PUBLISHED",
            category="METHODOLOGY"
        )

        # Authenticated student
        self.student = User.objects.create_user(username="search_student@univ.edu", password="Password123!")
        StudentProfile.objects.create(user=self.student, school=self.school_eneam, level=self.level, filiere=self.filiere_eneam)

    def test_global_search_page_accessible(self):
        """Global search page responds with 200 OK for anonymous and logged-in users."""
        res_anon = self.client.get(reverse("academics:global_search"))
        self.assertEqual(res_anon.status_code, 200)

        self.client.login(username="search_student@univ.edu", password="Password123!")
        res_auth = self.client.get(reverse("academics:global_search"))
        self.assertEqual(res_auth.status_code, 200)

    def test_search_across_all_models_and_partial_matching(self):
        """Search term 'prob' matches Subject, Exam, Summary, Guide, and Article case-insensitively."""
        res = self.client.get(reverse("academics:global_search") + "?q=prob")
        self.assertEqual(res.status_code, 200)

        subjects = [item["object"] for item in res.context["subjects_results"]]
        exams = [item["object"] for item in res.context["exams_results"]]
        summaries = [item["object"] for item in res.context["summaries_results"]]
        guides = [item["object"] for item in res.context["guides_results"]]
        articles = [item["object"] for item in res.context["articles_results"]]

        self.assertIn(self.subject, subjects)
        self.assertIn(self.exam_published, exams)
        self.assertIn(self.summary_published, summaries)
        self.assertIn(self.guide_published, guides)
        self.assertIn(self.article_published, articles)

    def test_draft_content_not_exposed_in_search(self):
        """Unpublished draft exams or content are never exposed in search results."""
        res = self.client.get(reverse("academics:global_search") + "?q=Secret")
        exams = [item["object"] for item in res.context["exams_results"]]
        self.assertNotIn(self.exam_draft, exams)
        self.assertEqual(res.context["total_results_count"], 0)

    def test_empty_and_no_results_search_behavior(self):
        """Empty query and zero-match query render clean professional states."""
        res_empty = self.client.get(reverse("academics:global_search"))
        self.assertEqual(res_empty.context["total_results_count"], 0)

        res_no_match = self.client.get(reverse("academics:global_search") + "?q=xyznonexistentterm")
        self.assertEqual(res_no_match.context["total_results_count"], 0)
        self.assertContains(res_no_match, "Aucun résultat trouvé")

    def test_category_filtering(self):
        """Category filter restricts search results to specific model types."""
        res_exams_only = self.client.get(reverse("academics:global_search") + "?q=prob&category=exams")
        self.assertTrue(len(res_exams_only.context["exams_results"]) > 0)
        self.assertEqual(len(res_exams_only.context["summaries_results"]), 0)
        self.assertEqual(len(res_exams_only.context["guides_results"]), 0)

    def test_academic_context_prioritization(self):
        """Results belonging to student's academic filière are prioritized."""
        self.client.login(username="search_student@univ.edu", password="Password123!")
        res = self.client.get(reverse("academics:global_search") + "?q=prob")
        exams_results = res.context["exams_results"]
        if exams_results:
            self.assertTrue(exams_results[0]["is_priority"])


class GlobalErrorPagesAndUIStatesTest(TestCase):
    """Test suite for Phase 7: Professional Error Pages & Global UI States."""

    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="Licence 1", code="L1")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")
        self.subject = Subject.objects.create(semester=self.semester, name="Algorithmique")

        # Premium Exam
        self.premium_exam = Exam.objects.create(
            title="Examen Premium Algorithmique",
            subject=self.subject,
            filiere=self.filiere,
            level=self.level,
            academic_year=self.year,
            semester=self.semester,
            year="2025",
            exam_type="EXAM",
            is_published=True,
            is_free=False
        )

        self.student = User.objects.create_user(username="error_student@univ.edu", password="Password123!")

    def test_custom_403_error_page(self):
        """Custom 403 page renders with status 403, Font Awesome shield icon, professional copy, and no stack trace."""
        res = self.client.get(reverse("academics:error_403"))
        self.assertEqual(res.status_code, 403)
        self.assertContains(res, "Accès refusé", status_code=403)
        self.assertContains(res, "fa-shield-halved", status_code=403)
        self.assertNotContains(res, "Traceback", status_code=403)
        self.assertNotContains(res, "PermissionDenied", status_code=403)

    def test_custom_404_error_page(self):
        """Custom 404 page renders with status 404, Font Awesome compass icon, search input, and no debug output."""
        res = self.client.get(reverse("academics:error_404"))
        self.assertEqual(res.status_code, 404)
        self.assertContains(res, "Page introuvable", status_code=404)
        self.assertContains(res, "fa-compass", status_code=404)
        self.assertContains(res, "Rechercher une épreuve", status_code=404)
        self.assertNotContains(res, "Resolver404", status_code=404)

    def test_custom_500_error_page(self):
        """Custom 500 page renders as standalone page with status 500, Font Awesome warning icon, and no internal details."""
        res = self.client.get(reverse("academics:error_500"))
        self.assertEqual(res.status_code, 500)
        self.assertContains(res, "Une erreur est survenue", status_code=500)
        self.assertContains(res, "fa-triangle-exclamation", status_code=500)
        self.assertNotContains(res, "Traceback", status_code=500)
        self.assertNotContains(res, "django.db", status_code=500)

    def test_premium_lock_distinct_from_403(self):
        """Premium lock redirects/displays value-driven Pass conversion page rather than returning 403 Forbidden."""
        self.client.login(username="error_student@univ.edu", password="Password123!")
        res = self.client.get(reverse("exams:detail", kwargs={"pk": self.premium_exam.pk}))
        self.assertEqual(res.status_code, 200)
        # Should display Pass Semestre unlock CTA, not a 403 Forbidden page!
        self.assertContains(res, "Débloque cette épreuve")
        self.assertNotContains(res, "Accès refusé (403)")

    def test_zero_emoji_policy_in_error_pages(self):
        """Verify zero emojis appear in 403, 404, and 500 error pages."""
        emojis = ["🔒", "⚡", "🚀", "📚", "📄", "🎯", "💡", "✓", "❌", "⚠️"]
        for endpoint in ["academics:error_403", "academics:error_404", "academics:error_500"]:
            status_code = 403 if "403" in endpoint else (404 if "404" in endpoint else 500)
            res = self.client.get(reverse(endpoint))
            content = res.content.decode("utf-8")
            for emoji in emojis:
                self.assertNotIn(emoji, content, f"Emoji {emoji} found in response for {endpoint}")

