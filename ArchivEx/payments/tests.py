import hmac
import hashlib
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from exams.models import Exam
from payments.models import SemesterAccess, Payment
from payments.services import (
    normalize_benin_phone,
    detect_operator,
    generate_external_reference,
    activate_pass_for_payment,
    create_fedapay_transaction,
    verify_fedapay_webhook_signature,
    handle_fedapay_webhook_event,
    verify_and_sync_fedapay_transaction,
    get_fedapay_base_url,
)
from subscriptions.models import UserSubscription
from subscriptions.services import (
    has_user_valid_pass,
    can_user_access_exam_pdf,
    can_user_access_correction,
    can_user_access_summary,
)

User = get_user_model()


@override_settings(
    FEDAPAY_SECRET_KEY="sk_sandbox_mock_fedapay_secret_key_123",
    FEDAPAY_PUBLIC_KEY="pk_sandbox_mock_fedapay_public_key_456",
    FEDAPAY_ENVIRONMENT="sandbox",
    FEDAPAY_WEBHOOK_SECRET="wh_sandbox_fedapay_secret_789",
    FEDAPAY_CURRENCY="XOF",
    PASS_SEMESTRE_PRIX_DEFAUT=4500,
)
class PaymentCoreAndUtilityTests(TestCase):
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
        """Détection correcte des opérateurs béninois (MTN, Moov, Celtiis)."""
        self.assertEqual(detect_operator("0150196407"), "mtn")
        self.assertEqual(detect_operator("53000000"), "mtn")
        self.assertEqual(detect_operator("0195000000"), "moov")
        self.assertEqual(detect_operator("60000000"), "moov")
        self.assertEqual(detect_operator("0140123456"), "celtiis")

    def test_unique_external_reference_generation(self):
        """Génération de références externes uniques format ARCHIVEX-PASS-YYYY-XXXXXX."""
        ref1 = generate_external_reference()
        ref2 = generate_external_reference()
        self.assertTrue(ref1.startswith("ARCHIVEX-PASS-"))
        self.assertNotEqual(ref1, ref2)

    def test_user_can_access_pass_semestre_page(self):
        """Un utilisateur connecté accède à la page Pass Semestre avec le prix de 4500 FCFA."""
        self.client.login(username="etudiant_test", password="Password123!")
        res = self.client.get(reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "4500")

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

    def test_direct_access_to_payment_success_does_not_activate_pass(self):
        """L'accès direct à /payment/success/ n'active PAS le Pass sans confirmation serveur."""
        self.client.login(username="etudiant_test", password="Password123!")
        res = self.client.get(reverse("payment_success_return"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))


@override_settings(
    FEDAPAY_SECRET_KEY="sk_sandbox_mock_fedapay_secret_key_123",
    FEDAPAY_PUBLIC_KEY="pk_sandbox_mock_fedapay_public_key_456",
    FEDAPAY_ENVIRONMENT="sandbox",
    FEDAPAY_WEBHOOK_SECRET="wh_sandbox_fedapay_secret_789",
    FEDAPAY_CURRENCY="XOF",
    PASS_SEMESTRE_PRIX_DEFAUT=4500,
)
class FedaPayIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="FASHS", code="FASHS", slug="fashs", is_active=True)
        self.level = Level.objects.create(name="L2", code="L2")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Sociologie")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 3")

        self.student = User.objects.create_user(
            username="etudiant_fedapay",
            email="fedapay.student@univ.bj",
            first_name="Bio",
            last_name="Guerra",
            password="SecurePassword123!"
        )

    def test_fedapay_configuration_settings(self):
        """Les variables de configuration FedaPay sont correctement définies."""
        self.assertTrue(hasattr(settings, "FEDAPAY_SECRET_KEY"))
        self.assertTrue(hasattr(settings, "FEDAPAY_PUBLIC_KEY"))
        self.assertTrue(hasattr(settings, "FEDAPAY_ENVIRONMENT"))
        self.assertTrue(hasattr(settings, "FEDAPAY_WEBHOOK_SECRET"))
        self.assertEqual(settings.FEDAPAY_CURRENCY, "XOF")
        self.assertEqual(settings.PASS_SEMESTRE_PRIX_DEFAUT, 4500)

    def test_get_fedapay_base_url(self):
        """L'URL de l'API change dynamiquement entre sandbox et live."""
        with override_settings(FEDAPAY_ENVIRONMENT="sandbox"):
            self.assertEqual(get_fedapay_base_url(), "https://sandbox-api.fedapay.com/v1")
        with override_settings(FEDAPAY_ENVIRONMENT="live"):
            self.assertEqual(get_fedapay_base_url(), "https://api.fedapay.com/v1")

    def test_celtiis_operator_detection(self):
        """Les numéros de l'opérateur Celtiis Bénin sont correctement détectés."""
        self.assertEqual(detect_operator("0140123456"), "celtiis")
        self.assertEqual(detect_operator("+229 01 41 23 45 67"), "celtiis")
        self.assertEqual(detect_operator("0192345678"), "celtiis")
        self.assertEqual(detect_operator("0193456789"), "celtiis")

    @patch("payments.services.requests.post")
    def test_initiate_payment_redirects_to_fedapay_checkout_url(self, mock_post):
        """L'initiation de paiement appelle l'API FedaPay et redirige vers checkout_url."""
        # 1er appel: POST /transactions -> retourne tx_id 42
        mock_tx_response = MagicMock()
        mock_tx_response.status_code = 201
        mock_tx_response.json.return_value = {
            "v1/transaction": {
                "id": 42,
                "status": "pending",
                "amount": 4500,
            }
        }

        # 2e appel: POST /transactions/42/token -> retourne l'URL de paiement
        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "token": "tok_fedapay_xyz123",
            "url": "https://checkout.fedapay.com/token/tok_fedapay_xyz123",
        }

        mock_post.side_effect = [mock_tx_response, mock_token_response]

        self.client.force_login(self.student)
        res = self.client.post(
            reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
            {"phone_number": "0150196407"},
        )

        self.assertEqual(res.status_code, 302)
        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.fedapay_transaction_id, "42")
        self.assertEqual(payment.fedapay_checkout_url, "https://checkout.fedapay.com/token/tok_fedapay_xyz123")
        self.assertEqual(payment.gateway_reference, "42")
        self.assertRedirects(res, "https://checkout.fedapay.com/token/tok_fedapay_xyz123", fetch_redirect_response=False)

    @patch("payments.services.requests.post")
    def test_initiate_payment_fedapay_api_error_handles_gracefully(self, mock_post):
        """Une erreur de l'API FedaPay marque le paiement REJECTED sans lever d'exception 500."""
        mock_res = MagicMock()
        mock_res.status_code = 400
        mock_res.json.return_value = {
            "message": "Erreur de validation du montant ou numéro",
        }
        mock_post.return_value = mock_res

        self.client.force_login(self.student)
        res = self.client.post(
            reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
            {"phone_number": "0150196407"},
        )

        self.assertEqual(res.status_code, 302)
        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.STATUS_REJECTED)

    def test_fedapay_webhook_signature_verification_valid_and_tampered(self):
        """Vérifie la robustesse de la signature HMAC-SHA256 FedaPay."""
        raw_body = b'{"name":"transaction.approved","entity":{"id":100}}'
        secret = settings.FEDAPAY_WEBHOOK_SECRET.encode("utf-8")
        valid_digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()

        # Format 1: direct hex
        self.assertTrue(verify_fedapay_webhook_signature(raw_body, valid_digest))
        # Format 2: s=<hex>
        self.assertTrue(verify_fedapay_webhook_signature(raw_body, f"s={valid_digest}"))
        # Signature altérée
        self.assertFalse(verify_fedapay_webhook_signature(raw_body, "s=bad_sig_abc123"))

        # Format 3: avec horodatage t=<timestamp>,s=<sig>
        ts = "1728345600"
        ts_body = f"{ts}.".encode("utf-8") + raw_body
        ts_digest = hmac.new(secret, ts_body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_fedapay_webhook_signature(raw_body, f"t={ts},s={ts_digest}"))

    def test_fedapay_webhook_transaction_approved_activates_pass(self):
        """Le webhook transaction.approved valide le paiement et active le pass semestre de manière idempotente."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-FEDAPAY-001",
            fedapay_transaction_id="101",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "name": "transaction.approved",
            "entity": {
                "id": 101,
                "reference": payment.external_reference,
                "status": "approved",
                "custom_metadata": {
                    "external_reference": payment.external_reference,
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret = settings.FEDAPAY_WEBHOOK_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:fedapay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_FEDAPAY_SIGNATURE=f"s={sig_hex}"
        )

        self.assertEqual(res.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_APPROVED)
        self.assertTrue(has_user_valid_pass(self.student, self.semester))

        # Idempotence: un second envoi ne déclenche pas d'erreur
        res2 = self.client.post(
            reverse("payments:fedapay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_FEDAPAY_SIGNATURE=f"s={sig_hex}"
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json().get("status"), "already_approved")

    def test_fedapay_webhook_transaction_declined_marks_rejected(self):
        """Le webhook transaction.declined marque le paiement comme rejeté."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-FEDAPAY-002",
            fedapay_transaction_id="102",
            status=Payment.STATUS_PENDING,
        )

        payload = {
            "name": "transaction.declined",
            "entity": {
                "id": 102,
                "status": "declined",
                "custom_metadata": {
                    "external_reference": payment.external_reference,
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret = settings.FEDAPAY_WEBHOOK_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        res = self.client.post(
            reverse("payments:fedapay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_FEDAPAY_SIGNATURE=f"s={sig_hex}"
        )

        self.assertEqual(res.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_REJECTED)
        self.assertFalse(has_user_valid_pass(self.student, self.semester))

    @patch("payments.services.requests.get")
    def test_verify_and_sync_fedapay_transaction_activates_pass(self, mock_get):
        """L'interrogation active (GET /v1/transactions/{id}) synchronise le statut et active le pass."""
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-SYNC-FEDA-1",
            fedapay_transaction_id="202",
            status=Payment.STATUS_PENDING,
        )

        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "v1/transaction": {
                "id": 202,
                "status": "approved",
                "amount": 4500,
            }
        }
        mock_get.return_value = mock_res

        self.client.force_login(self.student)
        url = reverse("payments:payment_return", kwargs={"reference": payment.external_reference})
        res = self.client.get(f"{url}?id=202")

        self.assertEqual(res.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_APPROVED)
        self.assertTrue(has_user_valid_pass(self.student, self.semester))

    def test_fedapay_secret_keys_not_exposed_in_html(self):
        """Aucune clé secrète FedaPay n'est exposée dans le HTML envoyé au navigateur."""
        self.client.force_login(self.student)
        res = self.client.get(reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertNotIn(settings.FEDAPAY_SECRET_KEY, html)
        self.assertNotIn(settings.FEDAPAY_WEBHOOK_SECRET, html)


@override_settings(
    FEDAPAY_SECRET_KEY="sk_sandbox_mock_fedapay_secret_key_123",
    FEDAPAY_PUBLIC_KEY="pk_sandbox_mock_fedapay_public_key_456",
    FEDAPAY_ENVIRONMENT="sandbox",
    FEDAPAY_WEBHOOK_SECRET="wh_sandbox_fedapay_secret_789",
    FEDAPAY_CURRENCY="XOF",
    PASS_SEMESTRE_PRIX_DEFAUT=4500,
)
class PaymentEndToEndUnlockTests(TestCase):
    """
    Test complet de bout en bout (End-to-End) :
    1. L'épreuve principale, sa correction et sa fiche résumé sont STRICTEMENT verrouillées pour l'étudiant.
    2. L'étudiant initie le paiement (création du Payment PENDING).
    3. Le paiement est validé (soit par Webhook FedaPay, soit par retour avec synchronisation active).
    4. Dès validation :
       - Le Pass Semestre s'active instantanément.
       - can_user_access_exam_pdf devient True.
       - can_user_access_correction devient True.
       - can_user_access_summary devient True.
       - Le lecteur plein écran (student_viewer) affiche le document avec succès (HTTP 200).
    """

    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="IFRI", code="IFRI", slug="ifri", is_active=True)
        self.level = Level.objects.create(name="L3", code="L3")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Génie Logiciel")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 5")

        self.subject = Subject.objects.create(
            name="Architecture Logicielle",
            code="ARCH501",
            semester=self.semester,
            is_free=False,
            is_free_correction=False,
        )

        dummy_pdf = SimpleUploadedFile("test_epreuve.pdf", b"%PDF-1.4 mock content", content_type="application/pdf")
        dummy_corr = SimpleUploadedFile("test_corr.pdf", b"%PDF-1.4 correction content", content_type="application/pdf")
        dummy_sum = SimpleUploadedFile("test_sum.pdf", b"%PDF-1.4 resume content", content_type="application/pdf")

        self.exam = Exam.objects.create(
            title="Examen Session Normale 2025",
            exam_type="examen",
            year=2025,
            level=self.level,
            academic_year=self.year,
            subject=self.subject,
            semester=self.semester,
            filiere=self.filiere,
            file=dummy_pdf,
            correction_file=dummy_corr,
            summary_file=dummy_sum,
            is_published=True,
            is_free=False,
            is_free_correction=False,
        )

        self.student = User.objects.create_user(
            username="student_e2e",
            email="student_e2e@univ.bj",
            first_name="Koffi",
            last_name="Mensah",
            password="SecurePassword123!"
        )

    def test_end_to_end_payment_unlocks_all_exam_resources(self):
        """Vérifie le déverrouillage automatique complet des épreuves, corrections et résumés post-paiement."""
        # --- ÉTAPE 1 : AVANT PAIEMENT (RESSOURCES TOTALEMENT VERROUILLÉES) ---
        self.assertFalse(has_user_valid_pass(self.student, self.semester))
        self.assertFalse(can_user_access_exam_pdf(self.student, self.exam))
        self.assertFalse(can_user_access_correction(self.student, self.exam))
        self.assertFalse(can_user_access_summary(self.student, self.exam))

        # Connexion de l'étudiant
        self.client.force_login(self.student)

        # L'accès au lecteur sécurisé avant paiement redirige vers la page d'achat du Pass
        res_viewer_before = self.client.get(
            reverse("exams:student_viewer", kwargs={"pk": self.exam.pk}) + "?type=exam"
        )
        self.assertEqual(res_viewer_before.status_code, 302)
        self.assertIn(f"/pass/{self.semester.id}/", res_viewer_before.url)

        # --- ÉTAPE 2 : INITIATION DU PAIEMENT ---
        with patch("payments.services.requests.post") as mock_post:
            mock_tx = MagicMock(status_code=201)
            mock_tx.json.return_value = {
                "v1/transaction": {"id": 999, "status": "pending", "amount": 4500}
            }
            mock_tok = MagicMock(status_code=200)
            mock_tok.json.return_value = {
                "token": "tok_e2e_999",
                "url": "https://checkout.fedapay.com/token/tok_e2e_999"
            }
            mock_post.side_effect = [mock_tx, mock_tok]

            res_init = self.client.post(
                reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id}),
                {"phone_number": "0150196407"},
            )
            self.assertEqual(res_init.status_code, 302)
            self.assertEqual(res_init.url, "https://checkout.fedapay.com/token/tok_e2e_999")

        payment = Payment.objects.filter(user=self.student, semester=self.semester).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.fedapay_transaction_id, "999")

        # Avant approbation, les ressources sont TOUJOURS verrouillées
        self.assertFalse(has_user_valid_pass(self.student, self.exam))

        # --- ÉTAPE 3 : NOTIFICATION WEBHOOK FEDAPAY APPROUVÉE ---
        payload = {
            "name": "transaction.approved",
            "entity": {
                "id": 999,
                "reference": payment.external_reference,
                "status": "approved",
                "amount": 4500,
                "custom_metadata": {
                    "external_reference": payment.external_reference,
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        secret = settings.FEDAPAY_WEBHOOK_SECRET.encode("utf-8")
        sig_hex = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        res_webhook = self.client.post(
            reverse("payments:fedapay_webhook"),
            data=body_bytes,
            content_type="application/json",
            HTTP_X_FEDAPAY_SIGNATURE=f"s={sig_hex}"
        )
        self.assertEqual(res_webhook.status_code, 200)

        # --- ÉTAPE 4 : VÉRIFICATION DU DÉVERROUILLAGE AUTOMATIQUE IMMÉDIAT ---
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_APPROVED)
        self.assertIsNotNone(payment.paid_at)

        # 1. Le Pass Semestre est validé
        self.assertTrue(has_user_valid_pass(self.student, self.semester))
        self.assertTrue(has_user_valid_pass(self.student, self.exam))

        # 2. L'épreuve principale est déverrouillée
        self.assertTrue(can_user_access_exam_pdf(self.student, self.exam))

        # 3. La correction est déverrouillée
        self.assertTrue(can_user_access_correction(self.student, self.exam))

        # 4. Le résumé est déverrouillé
        self.assertTrue(can_user_access_summary(self.student, self.exam))

        # 5. Le lecteur d'épreuve est directement accessible (HTTP 200)
        res_viewer_exam = self.client.get(
            reverse("exams:student_viewer", kwargs={"pk": self.exam.pk}) + "?type=exam"
        )
        self.assertEqual(res_viewer_exam.status_code, 200)

        # 6. Le lecteur de correction est directement accessible (HTTP 200)
        res_viewer_corr = self.client.get(
            reverse("exams:student_viewer", kwargs={"pk": self.exam.pk}) + "?type=correction"
        )
        self.assertEqual(res_viewer_corr.status_code, 200)

        # 7. Le lecteur de résumé est directement accessible (HTTP 200)
        res_viewer_sum = self.client.get(
            reverse("exams:student_viewer", kwargs={"pk": self.exam.pk}) + "?type=summary"
        )
        self.assertEqual(res_viewer_sum.status_code, 200)

    @patch("payments.services.requests.get")
    def test_end_to_end_payment_via_return_sync_unlocks_immediately(self, mock_get):
        """
        Vérifie la résilience : Si le webhook a du retard, la simple redirection de retour
        interroge l'API FedaPay et déverrouille immédiatement toutes les épreuves.
        """
        payment = Payment.objects.create(
            user=self.student,
            semester=self.semester,
            amount=4500,
            currency="XOF",
            external_reference="ARCHIVEX-PASS-E2E-RETURN",
            fedapay_transaction_id="888",
            status=Payment.STATUS_PENDING,
        )

        self.assertFalse(can_user_access_exam_pdf(self.student, self.exam))

        mock_res = MagicMock(status_code=200)
        mock_res.json.return_value = {
            "v1/transaction": {
                "id": 888,
                "status": "approved",
                "amount": 4500,
            }
        }
        mock_get.return_value = mock_res

        self.client.force_login(self.student)
        url = reverse("payments:payment_return", kwargs={"reference": payment.external_reference})
        res_return = self.client.get(f"{url}?id=888")

        self.assertEqual(res_return.status_code, 200)
        self.assertContains(res_return, "Paiement confirmé")

        # Vérification du déverrouillage immédiat
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_APPROVED)
        self.assertTrue(has_user_valid_pass(self.student, self.exam))
        self.assertTrue(can_user_access_exam_pdf(self.student, self.exam))
        self.assertTrue(can_user_access_correction(self.student, self.exam))
        self.assertTrue(can_user_access_summary(self.student, self.exam))
