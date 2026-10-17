from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from exams.models import Exam
from payments.models import SemesterAccess, Payment
from subscriptions.models import SubscriptionPlan, UserSubscription
from subscriptions.services import (
    can_user_access,
    can_user_access_exam_pdf,
    can_user_access_correction,
    has_user_valid_pass,
)

User = get_user_model()


class SubscriptionsAndAccessControlTest(TestCase):
    def setUp(self):
        self.school_a = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_b = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)

        self.level_l1 = Level.objects.create(name="Licence 1", code="L1", school=self.school_a)

        self.filiere_a = Filiere.objects.create(school=self.school_a, level=self.level_l1, name="Informatique de Gestion")
        self.filiere_b = Filiere.objects.create(school=self.school_b, level=self.level_l1, name="Lettres Modernes")

        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester_a = Semester.objects.create(filiere=self.filiere_a, academic_year=self.year, label="Semestre 1", number=1)
        self.semester_b = Semester.objects.create(filiere=self.filiere_b, academic_year=self.year, label="Semestre 1", number=1)

        self.subject_a = Subject.objects.create(semester=self.semester_a, name="Algorithmique", is_free=False)
        self.subject_b = Subject.objects.create(semester=self.semester_b, name="Linguistique", is_free=False)

        self.exam_free = Exam.objects.create(
            title="Examen Gratuit",
            subject=self.subject_a,
            semester=self.semester_a,
            filiere=self.filiere_a,
            level=self.level_l1,
            academic_year=self.year,
            exam_type="examen",
            year=2024,
            is_free=True,
            is_published=True
        )

        self.exam_premium_a = Exam.objects.create(
            title="Examen Premium ENEAM",
            subject=self.subject_a,
            semester=self.semester_a,
            filiere=self.filiere_a,
            level=self.level_l1,
            academic_year=self.year,
            exam_type="examen",
            year=2024,
            is_free=False,
            is_published=True
        )

        self.exam_premium_b = Exam.objects.create(
            title="Examen Premium FLASH",
            subject=self.subject_b,
            semester=self.semester_b,
            filiere=self.filiere_b,
            level=self.level_l1,
            academic_year=self.year,
            exam_type="examen",
            year=2024,
            is_free=False,
            is_published=True
        )

        self.student = User.objects.create_user(username="student@test.com", password="Password123!")

    def test_free_resource_access(self):
        """Toutes les épreuves sont accessibles sans condition à tous les étudiants."""
        self.assertTrue(can_user_access_exam_pdf(self.student, self.exam_free))
        self.assertTrue(can_user_access(self.student, self.exam_free))
        self.assertTrue(can_user_access_exam_pdf(None, self.exam_free))

    def test_unsubscribed_premium_access_denied(self):
        """Les corrigés sont strictement réservés aux abonnés avec Pass."""
        self.assertFalse(can_user_access_correction(self.student, self.exam_premium_a))
        self.assertFalse(has_user_valid_pass(self.student, self.exam_premium_a))

    def test_legacy_semester_access_compatibility(self):
        """Legacy SemesterAccess débloque les corrigés du semestre correspondant."""
        SemesterAccess.objects.create(
            user=self.student,
            school=self.school_a,
            level=self.level_l1,
            filiere=self.filiere_a,
            academic_year=self.year,
            semester=self.semester_a,
            activated_at=timezone.now()
        )
        self.assertTrue(can_user_access_correction(self.student, self.exam_premium_a))
        self.assertFalse(can_user_access_correction(self.student, self.exam_premium_b))

    def test_v2_semester_subscription_scope(self):
        """UserSubscription avec portée semestre débloque uniquement les corrigés de ce semestre."""
        UserSubscription.objects.create(
            user=self.student,
            semester=self.semester_a,
            filiere=self.filiere_a,
            school=self.school_a,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
            is_active=True
        )
        self.assertTrue(can_user_access_correction(self.student, self.exam_premium_a))
        self.assertFalse(can_user_access_correction(self.student, self.exam_premium_b))

    def test_v2_school_wide_subscription_scope(self):
        """UserSubscription avec portée école débloque les corrigés de toute l'école."""
        UserSubscription.objects.create(
            user=self.student,
            school=self.school_a,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=365),
            is_active=True
        )
        self.assertTrue(can_user_access_correction(self.student, self.exam_premium_a))
        self.assertFalse(can_user_access_correction(self.student, self.exam_premium_b))

    def test_expired_subscription_denies_access(self):
        """Un abonnement expiré refuse l'accès aux corrigés."""
        UserSubscription.objects.create(
            user=self.student,
            school=self.school_a,
            start_date=timezone.now() - timedelta(days=60),
            end_date=timezone.now() - timedelta(days=1),  # Expiré hier
            is_active=True
        )
        self.assertFalse(can_user_access_correction(self.student, self.exam_premium_a))
