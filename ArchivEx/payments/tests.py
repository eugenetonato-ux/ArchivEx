from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere, AcademicYear, Semester
from payments.models import SemesterAccess, Payment
from subscriptions.models import UserSubscription

User = get_user_model()


class PaymentIdempotencyAndFlowTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="L1", code="L1")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")

        self.student = User.objects.create_user(username="student_pay@univ.edu", password="Password123!")

    def test_payment_initiation_and_confirmation(self):
        """Initiate payment and confirm via callback, activating SemesterAccess and UserSubscription."""
        self.client.login(username="student_pay@univ.edu", password="Password123!")

        # 1. Initiate payment (POST)
        init_res = self.client.post(reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}))
        self.assertEqual(init_res.status_code, 200)

        payment = Payment.objects.get(user=self.student, semester_access__semester=self.semester)
        self.assertEqual(payment.status, "en_attente")
        self.assertEqual(payment.amount, 2000)

        # 2. Confirm payment (POST callback simulation)
        confirm_res = self.client.post(reverse("payments:confirmer_paiement", kwargs={"payment_id": payment.id}))
        self.assertEqual(confirm_res.status_code, 200)

        payment.refresh_from_db()
        self.assertEqual(payment.status, "reussi")
        self.assertIsNotNone(payment.paid_at)

        # Check UserSubscription created
        sub_count = UserSubscription.objects.filter(user=self.student, semester=self.semester).count()
        self.assertEqual(sub_count, 1)

    def test_duplicate_callback_idempotency(self):
        """Duplicate successful callbacks must NOT create duplicate subscriptions or accesses."""
        self.client.login(username="student_pay@univ.edu", password="Password123!")

        self.client.post(reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}))
        payment = Payment.objects.get(user=self.student, semester_access__semester=self.semester)

        # First callback
        self.client.post(reverse("payments:confirmer_paiement", kwargs={"payment_id": payment.id}))

        # Second duplicate callback
        self.client.post(reverse("payments:confirmer_paiement", kwargs={"payment_id": payment.id}))

        # Assert exactly 1 UserSubscription exists
        sub_count = UserSubscription.objects.filter(user=self.student, semester=self.semester).count()
        self.assertEqual(sub_count, 1)
