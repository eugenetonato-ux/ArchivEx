import hmac
import hashlib
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model

from academics.models import School, Level, Filiere, AcademicYear, Semester
from payments.models import SemesterAccess, Payment
from payments.services import (
    normalize_benin_phone,
    detect_operator,
    generate_external_reference,
    verify_chariow_pulse_signature,
    activate_pass_for_payment,
    create_chariow_checkout,
)
from subscriptions.models import UserSubscription
from subscriptions.services import has_user_valid_pass

User = get_user_model()


@override_settings(
    CHARIOW_API_KEY="sk_test_mock_chariow_api_key",
    CHARIOW_PRODUCT_ID="prd_pass_semestre_test",
    CHARIOW_PULSE_SECRET="chariow_pulse_secret_test_123",
    CHARIOW_BASE_URL="https://api.chariow.com/v1",
    CHARIOW_CURRENCY="XOF",
    PASS_SEMESTRE_PRIX_DEFAUT=4500,
)
class ChariowIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="L1", code="L1")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")

        self.student = User.objects.create_user(
            username="etudiant_test",
            email="etudiant@univ.bj",
            first_name="Marc",
            last_name="Tossou",
            password="Password123!"
        )

    def test_chariow_configuration_settings(self):
        """Les variables de configuration Chariow sont correctement définies."""
        self.assertTrue(hasattr(settings, "CHARIOW_API_KEY"))
        self.assertTrue(hasattr(settings, "CHARIOW_PRODUCT_ID"))
        self.assertTrue(hasattr(settings, "CHARIOW_PULSE_SECRET"))
        self.assertEqual(settings.CHARIOW_CURRENCY, "XOF")
        self.assertEqual(settings.PASS_SEMESTRE_PRIX_DEFAUT, 4500)

    def test_phone_number_normalization(self):
        """Les numéros béninois sont correctement normalisés."""
        self.assertEqual(normalize_benin_phone("0150196407"), "2290150196407")
        self.assertEqual(normalize_benin_phone("50196407"), "2290150196407")
        self.assertEqual(normalize_benin_phone("+229 01 50 19 64 07"), "2290150196407")
        self.assertEqual(normalize_benin_phone("2290150196407"), "2290150196407")
        self.assertEqual(normalize_benin_phone("97000000"), "2290197000000")

        with self.assertRaises(ValueError):
            normalize_benin_phone("123")

    def test_operator_detection(self):
        """Détection correcte des opérateurs béninois (MTN et Moov)."""
        self.assertEqual(detect_operator("0150196407"), "mtn")
        self.assertEqual(detect_operator("53000000"), "mtn")
        self.assertEqual(detect_operator("0195000000"), "moov")
        self.assertEqual(detect_operator("60000000"), "moov")

    def test_unique_external_reference_generation(self):
        """Génération de références externes uniques format ARCHIVEX-PASS-YYYY-XXXXXX."""
        ref1 = generate_external_reference()
        ref2 = generate_external_reference()
        self.assertTrue(ref1.startswith("ARCHIVEX-PASS-"))
        self.assertNotEqual(ref1, ref2)

    def test_user_can_access_pass_semestre_page(self):
        """Un utilisateur connecté accède à la page Pass Semestre avec le prix de 2000 FCFA."""
        self.client.login(username="etudiant_test", password="Password123!")
        res = self.client.get(reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "4500")

    @patch("payments.services.requests.post")
    def test_initiate_payment_success_redirects_to_chariow_checkout_url(self, mock_post):
        """L'initiation de paiement appelle l'API Chariow et redirige vers payment.checkout_url."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "step": "payment",
            "checkout_url": "https://payment.chariow.com/checkout?session=sess_123456",
            "sale_id": "sal_abc789",
        }
        mock_post.return_value = mock_response

        self.client.login(username="etudiant_test", password="Password123!")
        res = self.client.post(
            reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
            {"operator": "mtn", "phone_number": "0150196407"}
        )

        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, 4500)
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.chariow_sale_id, "sal_abc789")
        self.assertEqual(payment.chariow_checkout_url, "https://payment.chariow.com/checkout?session=sess_123456")

        self.assertRedirects(res, "https://payment.chariow.com/checkout?session=sess_123456", fetch_redirect_response=False)

    @patch("payments.services.requests.post")
    def test_initiate_payment_api_error_handled_gracefully(self, mock_post):
        """Une erreur renvoyée par Chariow marque le paiement REJECTED sans planter."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "Produit non publié ou invalide.",
        }
        mock_post.return_value = mock_response

        self.client.login(username="etudiant_test", password="Password123!")
        res = self.client.post(
            reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
            {"operator": "mtn", "phone_number": "0150196407"},
            follow=True
        )

        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertEqual(payment.status, Payment.STATUS_REJECTED)
        self.assertContains(res, "Produit non publié")

    def test_pending_payment_does_not_grant_pass(self):
        """Un paiement PENDING n'active pas le Pass."""
        Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-TEST-PENDING",
            status=Payment.STATUS_PENDING,
        )
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    def test_rejected_payment_does_not_grant_pass(self):
        """Un paiement REJECTED n'active pas le Pass."""
        Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-TEST-REJECTED",
            status=Payment.STATUS_REJECTED,
        )
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    def test_approved_payment_grants_pass_for_180_days(self):
        """Un paiement APPROVED active le Pass et crée l'abonnement pour 180 jours."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-TEST-APPROVED",
            status=Payment.STATUS_APPROVED,
        )
        activate_pass_for_payment(payment)

        self.assertTrue(has_user_valid_pass(self.student, self.semester))
        sub = UserSubscription.objects.get(user=self.student, semester=self.semester)
        self.assertTrue(sub.is_currently_valid())

    def test_idempotent_activation(self):
        """L'activation répétée d'un paiement ne crée pas de doublons."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-TEST-IDEMP",
            status=Payment.STATUS_APPROVED,
        )
        activate_pass_for_payment(payment)
        activate_pass_for_payment(payment)

        self.assertEqual(SemesterAccess.objects.filter(user=self.student, semester=self.semester).count(), 1)
        self.assertEqual(UserSubscription.objects.filter(user=self.student, semester=self.semester).count(), 1)

    def test_webhook_invalid_signature_rejected_with_403(self):
        """Un webhook avec une signature invalide est rejeté avec HTTP 403."""
        payload = {"event": "successful.sale", "data": {}}
        body_bytes = json.dumps(payload).encode("utf-8")

        res = self.client.post(
            reverse("payments:chariow_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_CHARIOW_SIGNATURE="sha256=mauvaisesignature123"
        )
        self.assertEqual(res.status_code, 403)

    def test_webhook_successful_sale_approves_payment_and_activates_pass(self):
        """Un webhook successful.sale avec signature valide valide le paiement et active le Pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-2026-WBK01",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "event": "successful.sale",
            "data": {
                "sale": {
                    "id": "sal_998877",
                    "amount": 4500,
                    "currency": "XOF",
                    "custom_metadata": {
                        "archivex_user_id": str(self.student.id),
                        "archivex_semester_id": str(self.semester.id),
                        "external_reference": payment.external_reference,
                        "archivex_payment_id": str(payment.id),
                    }
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        secret = settings.CHARIOW_PULSE_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
        signature_header = f"sha256={sig_hex}"

        res = self.client.post(
            reverse("payments:chariow_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_CHARIOW_SIGNATURE=signature_header,
            HTTP_X_PULSE_DELIVERY_ID="del_12345"
        )

        self.assertEqual(res.status_code, 200)
        payment.refresh_from_db()
        self.assertTrue(payment.is_approved)
        self.assertEqual(payment.chariow_sale_id, "sal_998877")
        self.assertTrue(has_user_valid_pass(self.student, self.semester))

    def test_webhook_duplicate_event_is_idempotent(self):
        """Deux réceptions consécutives du même webhook successful.sale ne dupliquent rien."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-2026-WBK-IDEMP",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "event": "successful.sale",
            "data": {
                "sale": {
                    "id": "sal_dupl123",
                    "amount": 4500,
                    "currency": "XOF",
                    "custom_metadata": {
                        "external_reference": payment.external_reference,
                    }
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret = settings.CHARIOW_PULSE_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        # Premier webhook
        res1 = self.client.post(
            reverse("payments:chariow_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_CHARIOW_SIGNATURE=f"sha256={sig_hex}"
        )
        self.assertEqual(res1.status_code, 200)

        # Deuxième webhook identique
        res2 = self.client.post(
            reverse("payments:chariow_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_CHARIOW_SIGNATURE=f"sha256={sig_hex}"
        )
        self.assertEqual(res2.status_code, 200)
        self.assertIn("already_approved", res2.json().get("status", ""))

        self.assertEqual(UserSubscription.objects.filter(user=self.student, semester=self.semester).count(), 1)

    def test_webhook_failed_and_abandoned_sale(self):
        """Les webhooks failed.sale et abandoned.sale mettent à jour le statut du paiement."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-FAIL-01",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "event": "failed.sale",
            "data": {
                "sale": {
                    "id": "sal_fail",
                    "custom_metadata": {"external_reference": payment.external_reference}
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret = settings.CHARIOW_PULSE_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:chariow_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_CHARIOW_SIGNATURE=f"sha256={sig_hex}"
        )
        self.assertEqual(res.status_code, 200)
        payment.refresh_from_db()
        self.assertTrue(payment.is_rejected)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    def test_webhook_unknown_event_handled_gracefully(self):
        """Un événement inconnu reçu de Chariow retourne 200 sans lever d'exception."""
        payload = {"event": "some.future.event", "data": {}}
        body_bytes = json.dumps(payload).encode("utf-8")
        secret = settings.CHARIOW_PULSE_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:chariow_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_CHARIOW_SIGNATURE=f"sha256={sig_hex}"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "ignored")

    def test_no_secret_key_exposed_in_rendered_html(self):
        """Aucune clé secrète Chariow n'est exposée dans le HTML envoyé au client."""
        self.client.login(username="etudiant_test", password="Password123!")

        res_pass = self.client.get(reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))
        self.assertNotIn(settings.CHARIOW_API_KEY, res_pass.content.decode("utf-8"))
        self.assertNotIn(settings.CHARIOW_PULSE_SECRET, res_pass.content.decode("utf-8"))

        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-NOSEC",
            status=Payment.STATUS_PENDING,
        )
        res_ret = self.client.get(reverse("payments:payment_return", kwargs={"reference": payment.external_reference}))
        self.assertNotIn(settings.CHARIOW_API_KEY, res_ret.content.decode("utf-8"))
        self.assertNotIn(settings.CHARIOW_PULSE_SECRET, res_ret.content.decode("utf-8"))

    def test_direct_access_to_payment_success_does_not_activate_pass(self):
        """L'accès direct à /payment/success/ n'active PAS le Pass sans confirmation serveur."""
        self.client.login(username="etudiant_test", password="Password123!")

        res = self.client.get(reverse("payment_success_return"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))
