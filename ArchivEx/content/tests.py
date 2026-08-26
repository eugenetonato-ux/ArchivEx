from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from content.models import Summary, Guide, Article
from subscriptions.models import UserSubscription

User = get_user_model()


class ContentWorkflowAndSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="L1", code="L1", school=self.school)
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique de Gestion")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")
        self.subject = Subject.objects.create(semester=self.semester, name="Base de Données")

        self.student = User.objects.create_user(username="student@univ.edu", password="Password123!")

        # 1. DRAFT Summary (Should NOT be visible in public list)
        self.draft_summary = Summary.objects.create(
            title="Draft Summary",
            subject=self.subject,
            content="Brouillon non publié...",
            publication_status="DRAFT"
        )

        # 2. PUBLISHED Premium Summary
        self.published_summary = Summary.objects.create(
            title="Résumé SQL Avancé",
            subject=self.subject,
            content="<p>Contenu rédigé du résumé SQL.</p>",
            access_type="PREMIUM",
            publication_status="PUBLISHED"
        )

        # 3. PUBLISHED Guide
        self.guide = Guide.objects.create(
            title="Guide de Révision SQL",
            subject=self.subject,
            introduction="Intro guide...",
            objectives="Objectifs...",
            publication_status="PUBLISHED"
        )

        # 4. Article
        self.article = Article.objects.create(
            title="Comment Réviser Efficacement",
            category="METHODOLOGY",
            content="Contenu de l'article...",
            publication_status="PUBLISHED"
        )

    def test_draft_content_is_hidden_from_public(self):
        """Unpublished DRAFT content does not appear in public lists or detail views."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res = self.client.get(reverse("content:summary_list"))
        self.assertNotContains(res, "Draft Summary")

        res_detail = self.client.get(reverse("content:summary_detail", kwargs={"pk": self.draft_summary.id}))
        self.assertEqual(res_detail.status_code, 404)

    def test_published_summary_access_and_paywall(self):
        """Published summary is listed; paywall is enforced when unsubscribed."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res_list = self.client.get(reverse("content:summary_list"))
        self.assertContains(res_list, "Résumé SQL Avancé")

        # Unsubscribed -> Paywall active
        res_detail = self.client.get(reverse("content:summary_detail", kwargs={"pk": self.published_summary.id}))
        self.assertFalse(res_detail.context["has_access"])

        # Subscribed -> Access granted
        UserSubscription.objects.create(
            user=self.student,
            semester=self.semester,
            filiere=self.filiere,
            school=self.school,
            is_active=True
        )
        res_detail_sub = self.client.get(reverse("content:summary_detail", kwargs={"pk": self.published_summary.id}))
        self.assertTrue(res_detail_sub.context["has_access"])

    def test_article_public_accessibility(self):
        """Educational advice articles are accessible to all users."""
        res_list = self.client.get(reverse("content:article_list"))
        self.assertContains(res_list, "Comment Réviser Efficacement")

        res_detail = self.client.get(reverse("content:article_detail", kwargs={"pk": self.article.id}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.context["article"], self.article)

    def test_student_guide_accessibility(self):
        """Student Guide landing page renders correctly with featured methodology content."""
        res = self.client.get(reverse("content:student_guide"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Guide étudiant ArchivEx")
        self.assertContains(res, "Comment exploiter efficacement une ancienne épreuve")


