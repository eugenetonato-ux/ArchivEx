from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from ambassadors.models import Ambassador, AmbassadorSale
from academics.models import School, Level, Filiere, Semester, AcademicYear
from payments.models import Payment

User = get_user_model()


class AmbassadorTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Données académiques
        self.school = School.objects.create(name="ENEAM", code="ENEAM")
        self.level = Level.objects.create(name="Licence 1", code="L1")
        self.year = AcademicYear.objects.create(label="2024-2025")
        self.filiere = Filiere.objects.create(name="Informatique de Gestion", code="IG", school=self.school, level=self.level)
        self.semester = Semester.objects.create(number=1, filiere=self.filiere, academic_year=self.year, is_active=True)

        # Utilisateur étudiant
        self.student = User.objects.create_user(username="etudiant1", password="password123")

        # Ambassadeur test
        self.ambassador = Ambassador.objects.create(
            first_name="Marc",
            last_name="Dossou",
            phone_number="0197001122",
            discount_amount=200,
            commission_per_sale=500,
        )

    def test_ambassador_code_validation_requires_first_name(self):
        # Valide car contient "Marc"
        ok, res = self.ambassador.validate_code_candidate("MARC25")
        self.assertTrue(ok)
        self.assertEqual(res, "MARC25")

        # Invalide car ne contient pas "Marc"
        ok, err = self.ambassador.validate_code_candidate("PROMO2025")
        self.assertFalse(ok)
        self.assertIn("Marc", err)

        # Invalide caractères interdits
        ok, err = self.ambassador.validate_code_candidate("MARC 25!")
        self.assertFalse(ok)

    def test_ambassador_dashboard_and_code_set(self):
        url = reverse("ambassadors:dashboard", kwargs={"token": self.ambassador.access_token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Marc")

        # Définition du code
        resp = self.client.post(url, {"action": "set_code", "code": "MARC-S1"})
        self.ambassador.refresh_from_db()
        self.assertEqual(self.ambassador.code, "MARC-S1")

    def test_verify_code_api(self):
        self.ambassador.code = "MARC25"
        self.ambassador.save()

        api_url = reverse("ambassadors:verify_code_api")
        resp = self.client.get(f"{api_url}?code=MARC25")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["discount"], 200)
        self.assertEqual(data["final_price"], 4300)

        # Code inexistant
        resp = self.client.get(f"{api_url}?code=INEXISTANT")
        self.assertFalse(resp.json()["valid"])

    def test_pass_checkout_with_referral_code(self):
        self.ambassador.code = "MARC25"
        self.ambassador.save()

        self.client.login(username="etudiant1", password="password123")

        # Affichage avec ?ref=MARC25
        pass_url = reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id})
        resp = self.client.get(f"{pass_url}?ref=MARC25")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "4300")
        self.assertContains(resp, "MARC25")

        # Initiation du paiement avec code
        init_url = reverse("payments:initier_paiement", kwargs={"semester_id": self.semester.id})
        resp = self.client.post(init_url, {
            "phone_number": "0197000000",
            "operator": "mtn",
            "referral_code": "MARC25"
        })

        payment = Payment.objects.filter(user=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, 4300)
        self.assertEqual(payment.discount_amount, 200)
        self.assertEqual(payment.ambassador, self.ambassador)

        # Vérifier que AmbassadorSale est créé en PENDING
        sale = AmbassadorSale.objects.filter(payment=payment).first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.status, "PENDING")
        self.assertEqual(sale.commission_amount, 500)

        # Simulation d'approbation et activation
        from payments.services import activate_pass_for_payment
        payment.status = Payment.STATUS_APPROVED
        activate_pass_for_payment(payment)

        sale.refresh_from_db()
        self.assertEqual(sale.status, "APPROVED")
        self.assertEqual(self.ambassador.sales_count, 1)
        self.assertEqual(self.ambassador.total_earnings, 500)
        self.assertEqual(self.ambassador.pending_payout, 500)
