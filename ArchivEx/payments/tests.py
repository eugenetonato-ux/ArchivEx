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

    def test_payment_initiation_with_operators(self):
        """Initiate payment with valid operator (MTN, Moov, Celtiis) using server price."""
        self.client.login(username="student_sebpay@univ.edu", password="Password123!")

        res = self.client.post(
            reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
            {"operator": "mtn", "phone_number": "97000000"}
        )

        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, 4500)  # Montant déterminé par le serveur (4500 FCFA)
        self.assertEqual(payment.currency, "XOF")
        self.assertEqual(payment.operator, "mtn")
        self.assertEqual(payment.phone_number, "22997000000")
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertRedirects(res, reverse("payments:payment_pending", kwargs={"reference": payment.external_reference}))

    def test_webhook_valid_signature_approves_payment_and_activates_pass(self):
        """Valid HMAC signature webhook approves PENDING payment and activates Pass Semestre."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            operator="moov",
            phone_number="22997000000",
            external_reference="ARCHIVEX-PASS-2026-TEST01",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "external_reference": payment.external_reference,
            "status": "approved",
            "amount": 4500,
            "currency": "XOF",
            "id": "SEBPAY-TX-10001",
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret_key = settings.SEBPAY_SECRET_KEY.encode("utf-8")
        valid_signature = hmac.new(secret_key, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:sebpay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_SEBPAY_SIGNATURE=valid_signature
        )

        self.assertEqual(res.status_code, 200)

        payment.refresh_from_db()
        self.assertTrue(payment.is_approved)
        self.assertEqual(payment.sebpay_transaction_id, "SEBPAY-TX-10001")

        # Verify Pass activated
        self.assertTrue(has_user_valid_pass(self.student, self.semester))

    def test_webhook_invalid_signature_rejected(self):
        """Webhook with invalid HMAC signature is rejected with HTTP 403 Forbidden."""
        body_bytes = json.dumps({"external_reference": "REF123", "status": "approved"}).encode("utf-8")

        res = self.client.post(
            reverse("payments:sebpay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_SEBPAY_SIGNATURE="bad_fake_signature"
        )
        self.assertEqual(res.status_code, 403)

    def test_webhook_idempotency(self):
        """Duplicate webhook requests do not create duplicate accesses or subscriptions."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            operator="celtiis",
            phone_number="22997000000",
            external_reference="ARCHIVEX-PASS-2026-TEST02",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "external_reference": payment.external_reference,
            "status": "approved",
            "amount": 4500,
            "currency": "XOF",
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret_key = settings.SEBPAY_SECRET_KEY.encode("utf-8")
        signature = hmac.new(secret_key, body_bytes, hashlib.sha256).hexdigest()

        # First delivery
        self.client.post(reverse("payments:sebpay_webhook"), data=body_bytes, content_type="application/json", HTTP_X_SEBPAY_SIGNATURE=signature)

        # Duplicate delivery
        res2 = self.client.post(reverse("payments:sebpay_webhook"), data=body_bytes, content_type="application/json", HTTP_X_SEBPAY_SIGNATURE=signature)
        self.assertEqual(res2.status_code, 200)

        # Check single access and subscription
        self.assertEqual(SemesterAccess.objects.filter(user=self.student, semester=self.semester).count(), 1)
        self.assertEqual(UserSubscription.objects.filter(user=self.student, semester=self.semester).count(), 1)

    def test_pending_and_rejected_payment_do_not_grant_access(self):
        """PENDING or REJECTED payments leave Pass locked."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            operator="mtn",
            phone_number="22997000000",
            external_reference="ARCHIVEX-PASS-2026-TEST03",
            status=Payment.STATUS_PENDING,
        )

        # Verify access denied while PENDING
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

        # Reject payment
        payment.status = Payment.STATUS_REJECTED
        payment.save()

        # Verify access still denied when REJECTED
        self.assertFalse(has_user_valid_pass(self.student, self.semester))
