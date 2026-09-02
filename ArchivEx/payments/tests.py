import hmac
import hashlib
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model

from academics.models import School, Level, Filiere, AcademicYear, Semester
from payments.models import SemesterAccess, Payment
from payments.services import (
    normalize_benin_phone,
    generate_external_reference,
    verify_webhook_signature,
    activate_pass_for_payment,
)
from subscriptions.models import UserSubscription
from subscriptions.services import has_user_valid_pass

User = get_user_model()


class SebPayIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="L1", code="L1")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")

        self.student = User.objects.create_user(username="student_sebpay@univ.edu", password="Password123!")

    def test_sebpay_configuration_settings(self):
        """Settings load SebPay keys safely."""
        self.assertTrue(hasattr(settings, "SEBPAY_PUBLIC_KEY"))
        self.assertTrue(hasattr(settings, "SEBPAY_SECRET_KEY"))
        self.assertEqual(settings.SEBPAY_COUNTRY, "BJ")
        self.assertEqual(settings.SEBPAY_CURRENCY, "XOF")

    def test_phone_number_normalization(self):
        """Valid Beninese phone numbers are normalized to 229XXXXXXXX format."""
        self.assertEqual(normalize_benin_phone("97000000"), "22997000000")
        self.assertEqual(normalize_benin_phone("+229 97 00 00 00"), "22997000000")
        self.assertEqual(normalize_benin_phone("0197000000"), "2290197000000")
        self.assertEqual(normalize_benin_phone("22997000000"), "22997000000")

        with self.assertRaises(ValueError):
            normalize_benin_phone("123")

    def test_unique_external_reference_generation(self):
        """Unique external references follow ARCHIVEX-PASS-YYYY-XXXXXX format."""
        ref1 = generate_external_reference()
        ref2 = generate_external_reference()
        self.assertTrue(ref1.startswith("ARCHIVEX-PASS-"))
        self.assertNotEqual(ref1, ref2)

    def test_01_user_can_access_pass_semestre_page(self):
        """Test 1 : Un utilisateur connecté peut accéder à la page du Pass Semestre."""
        self.client.login(username="student_sebpay@univ.edu", password="Password123!")
        res = self.client.get(reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Pass Semestre")

    def test_02_payment_button_initiates_payment_and_creates_pending(self):
        """Test 2 : Le bouton de paiement initie le paiement et crée un enregistrement PENDING avec référence unique."""
        self.client.login(username="student_sebpay@univ.edu", password="Password123!")
        res = self.client.post(
            reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
            {"operator": "mtn", "phone_number": "97000000"}
        )
        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, getattr(settings, "PASS_SEMESTRE_PRIX_DEFAUT", 4500))
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertTrue(payment.external_reference.startswith("ARCHIVEX-PASS-"))

    def test_03_payment_return_page_renders_correctly(self):
        """Test 3 : L'URL de retour fonctionne et affiche le statut réel du paiement."""
        self.client.login(username="student_sebpay@univ.edu", password="Password123!")
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-RET01",
            status=Payment.STATUS_PENDING,
        )
        res = self.client.get(reverse("payments:payment_return", kwargs={"reference": payment.external_reference}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, payment.external_reference)

    def test_04_pending_payment_does_not_grant_pass(self):
        """Test 4 : Un paiement 'pending' n'active PAS le Pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-PEND",
            status=Payment.STATUS_PENDING,
        )
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    def test_05_rejected_payment_does_not_grant_pass(self):
        """Test 5 : Un paiement 'rejected' n'active PAS le Pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-REJ",
            status=Payment.STATUS_REJECTED,
        )
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    def test_06_approved_payment_grants_pass(self):
        """Test 6 : Un paiement 'approved' active le Pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-APP",
            status=Payment.STATUS_APPROVED,
        )
        activate_pass_for_payment(payment)
        self.assertTrue(has_user_valid_pass(self.student, self.semester))

    def test_07_already_processed_payment_idempotency(self):
        """Test 7 : Une transaction déjà traitée ne peut pas activer le Pass une deuxième fois."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-IDEMP",
            status=Payment.STATUS_APPROVED,
        )
        activate_pass_for_payment(payment)
        # Seconde activation
        activate_pass_for_payment(payment)

        self.assertEqual(SemesterAccess.objects.filter(user=self.student, semester=self.semester).count(), 1)
        self.assertEqual(UserSubscription.objects.filter(user=self.student, semester=self.semester).count(), 1)

    def test_08_webhook_invalid_signature_rejected(self):
        """Test 8 : Un webhook avec une signature invalide est rejeté avec HTTP 403."""
        body_bytes = json.dumps({"external_reference": "REF123", "status": "approved"}).encode("utf-8")
        res = self.client.post(
            reverse("payments:sebpay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_SEBPAY_SIGNATURE="signature_invalide"
        )
        self.assertEqual(res.status_code, 403)

    def test_09_webhook_valid_signature_approves_and_activates_pass(self):
        """Test 9 : Un webhook valide avec signature HMAC-SHA256 est correctement traité et active le Pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-WBOK",
            status=Payment.STATUS_PENDING,
        )
        payload = {
            "external_reference": payment.external_reference,
            "status": "approved",
            "amount": 4500,
            "currency": "XOF",
            "id": "SEBPAY-TX-55555",
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret_key = settings.SEBPAY_SECRET_KEY.encode("utf-8")
        signature = hmac.new(secret_key, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:sebpay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_SEBPAY_SIGNATURE=signature
        )

        self.assertEqual(res.status_code, 200)
        payment.refresh_from_db()
        self.assertTrue(payment.is_approved)
        self.assertTrue(has_user_valid_pass(self.student, self.semester))

    def test_10_webhook_mismatched_amount_or_currency_rejected(self):
        """Test 10 : Un webhook avec montant ou devise incorrecte n'active PAS le Pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-MISMATCH",
            status=Payment.STATUS_PENDING,
        )
        payload = {
            "external_reference": payment.external_reference,
            "status": "approved",
            "amount": 500,  # Montant falsifié
            "currency": "XOF",
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret_key = settings.SEBPAY_SECRET_KEY.encode("utf-8")
        signature = hmac.new(secret_key, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:sebpay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_SEBPAY_SIGNATURE=signature
        )

        self.assertEqual(res.status_code, 400)
        payment.refresh_from_db()
        self.assertFalse(payment.is_approved)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    def test_11_no_secret_key_exposed_in_rendered_html(self):
        """Test 11 : Aucune clé secrète n'est présente dans le HTML envoyé au navigateur."""
        self.client.login(username="student_sebpay@univ.edu", password="Password123!")

        res_pass = self.client.get(reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))
        self.assertNotIn(settings.SEBPAY_SECRET_KEY, res_pass.content.decode("utf-8"))

        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-NOSEC",
            status=Payment.STATUS_PENDING,
        )
        res_ret = self.client.get(reverse("payments:payment_return", kwargs={"reference": payment.external_reference}))
        self.assertNotIn(settings.SEBPAY_SECRET_KEY, res_ret.content.decode("utf-8"))

    def test_12_manual_access_to_payment_success_does_not_activate_pass(self):
        """Test 12 : Un accès manuel direct à /payment/success/ n'active PAS le Pass gratuitement."""
        self.client.login(username="student_sebpay@univ.edu", password="Password123!")

        # 1. Accès sans aucune transaction
        res = self.client.get(reverse("payment_success_return"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

        # 2. Accès avec une transaction PENDING
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-TEST-SUCCESS-ROUTE",
            status=Payment.STATUS_PENDING,
        )
        res_pending = self.client.get(reverse("payment_success_return"))
        self.assertEqual(res_pending.status_code, 200)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))
