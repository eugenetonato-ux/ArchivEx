from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from accounts.models import StudentProfile

User = get_user_model()


class AccountsAndAcademicsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school_eneam = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_flash = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)

        self.level_l1 = Level.objects.create(name="Licence 1", code="L1", school=self.school_eneam)
        self.level_l2 = Level.objects.create(name="Licence 2", code="L2", school=self.school_eneam)

        self.filiere_ig = Filiere.objects.create(school=self.school_eneam, level=self.level_l1, name="Informatique de Gestion", code="IG")
        self.filiere_fc = Filiere.objects.create(school=self.school_eneam, level=self.level_l1, name="Finance Comptabilité", code="FC")

        self.academic_year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere_ig, academic_year=self.academic_year, label="Semestre 1", number=1)
        self.subject = Subject.objects.create(semester=self.semester, name="Algorithmique", code="UE-ALGO")

    def test_academic_hierarchy_relationships(self):
        """Test valid School -> Level -> Filiere -> Semester -> Subject relationships."""
        self.assertEqual(self.filiere_ig.school, self.school_eneam)
        self.assertEqual(self.filiere_ig.level, self.level_l1)
        self.assertEqual(self.semester.filiere, self.filiere_ig)
        self.assertEqual(self.subject.semester, self.semester)

    def test_academic_lookup_apis(self):
        """Test API endpoints for levels and filieres filtering."""
        # Level API
        res = self.client.get(reverse("accounts:api_levels") + f"?school_id={self.school_eneam.id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("L1", res.content.decode("utf-8"))

        # Filiere API
        res = self.client.get(reverse("accounts:api_filieres") + f"?school_id={self.school_eneam.id}&level_id={self.level_l1.id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Informatique de Gestion", res.content.decode("utf-8"))

    def test_student_registration_flow(self):
        """Test valid and invalid student registration."""
        valid_data = {
            "first_name": "Jean",
            "last_name": "DOSSSOU",
            "email": "jean.dossou@gmail.com",
            "password": "Password123!",
            "school": self.school_eneam.id,
            "level": self.level_l1.id,
            "filiere": self.filiere_ig.id,
        }
        res = self.client.post(reverse("accounts:register"), valid_data)
        self.assertRedirects(res, reverse("accounts:dashboard"))

        user = User.objects.get(email="jean.dossou@gmail.com")
        self.assertEqual(user.first_name, "Jean")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.school, self.school_eneam)
        self.assertEqual(user.profile.filiere, self.filiere_ig)

        # Duplicate registration test (Logout first to test form validation)
        self.client.logout()
        res_dup = self.client.post(reverse("accounts:register"), valid_data)
        self.assertEqual(res_dup.status_code, 200)
        self.assertContains(res_dup, "Un compte avec cette adresse email existe déjà.")

    def test_student_registration_with_single_fullname_field(self):
        """Test registration using the new single 'full_name' (Nom et Prénom) field."""
        data = {
            "full_name": "Sophia Lokossou",
            "email": "sophia.lokossou@univ.edu",
            "password": "Password123!",
            "school": self.school_eneam.id,
            "level": self.level_l1.id,
            "filiere": self.filiere_ig.id,
        }
        res = self.client.post(reverse("accounts:register"), data)
        self.assertRedirects(res, reverse("accounts:dashboard"))

        user = User.objects.get(email="sophia.lokossou@univ.edu")
        self.assertEqual(user.first_name, "Sophia")
        self.assertEqual(user.last_name, "Lokossou")
        self.assertEqual(user.get_full_name(), "Sophia Lokossou")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.school, self.school_eneam)

    def test_student_data_isolation_idor_prevention(self):
        """Verify Student A cannot access or see Student B's profile or dashboard data."""
        user_a = User.objects.create_user(username="student_a@univ.edu", email="student_a@univ.edu", password="Password123!")
        profile_a = StudentProfile.objects.create(user=user_a, school=self.school_eneam, level=self.level_l1, filiere=self.filiere_ig)

        user_b = User.objects.create_user(username="student_b@univ.edu", email="student_b@univ.edu", password="Password123!")
        profile_b = StudentProfile.objects.create(user=user_b, school=self.school_flash, level=self.level_l2, filiere=self.filiere_fc)

        # Login as Student A
        self.client.login(username="student_a@univ.edu", password="Password123!")
        res = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["profile"], profile_a)
        self.assertNotEqual(res.context["profile"], profile_b)

    def test_login_unknown_identifier_proposes_registration(self):
        """When an unrecognized user tries to log in, propose registration with their email prefilled."""
        res = self.client.post(reverse("accounts:login"), {
            "username": "inconnu@gmail.com",
            "password": "RandomPassword123!"
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context["form"].account_not_found)
        self.assertFalse(res.context["form"].password_incorrect)
        self.assertContains(res, "Identifiant non reconnu")
        self.assertContains(res, "Créer un compte")
        self.assertContains(res, "inconnu%40gmail.com")

    def test_login_known_identifier_wrong_password_warns_incorrect_password(self):
        """When a recognized user types a wrong password, show password incorrect without proposing registration as a new account."""
        User.objects.create_user(
            username="existant@gmail.com",
            email="existant@gmail.com",
            password="CorrectPassword123!"
        )
        res = self.client.post(reverse("accounts:login"), {
            "username": "existant@gmail.com",
            "password": "WrongPassword999!"
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context["form"].account_not_found)
        self.assertTrue(res.context["form"].password_incorrect)
        self.assertContains(res, "Mot de passe incorrect")
        self.assertNotContains(res, "Rejoignez-nous en 30 secondes")

    def test_register_prefilled_email_from_query_param(self):
        """Register form correctly prefills the email passed via GET parameter."""
        res = self.client.get(reverse("accounts:register") + "?email=prefill.student@gmail.com")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "prefill.student@gmail.com")

    def test_single_session_per_account(self):
        """Verify that when a user logs in on a second client, the first client session is invalidated."""
        user = User.objects.create_user(
            username="concurrent@univ.edu",
            email="concurrent@univ.edu",
            password="Password123!"
        )
        StudentProfile.objects.create(
            user=user,
            school=self.school_eneam,
            level=self.level_l1,
            filiere=self.filiere_ig
        )

        client1 = Client()
        client2 = Client()

        # 1. Device 1 logs in
        res1 = client1.post(reverse("accounts:login"), {
            "username": "concurrent@univ.edu",
            "password": "Password123!"
        })
        self.assertRedirects(res1, reverse("accounts:dashboard"))
        
        # User active_session_key matches client1 session
        user.refresh_from_db()
        client1_session_key = client1.session.session_key
        self.assertEqual(user.active_session_key, client1_session_key)

        # Device 1 can access dashboard
        res_dash1 = client1.get(reverse("accounts:dashboard"))
        self.assertEqual(res_dash1.status_code, 200)

        # 2. Device 2 logs in on the same account
        res2 = client2.post(reverse("accounts:login"), {
            "username": "concurrent@univ.edu",
            "password": "Password123!"
        })
        self.assertRedirects(res2, reverse("accounts:dashboard"))

        # User active_session_key is now updated to client2 session
        user.refresh_from_db()
        client2_session_key = client2.session.session_key
        self.assertEqual(user.active_session_key, client2_session_key)
        self.assertNotEqual(client1_session_key, client2_session_key)

        # 3. Device 1 makes a subsequent request -> should be logged out & redirected to login
        res_dash1_invalid = client1.get(reverse("accounts:dashboard"), follow=True)
        self.assertRedirects(res_dash1_invalid, reverse("accounts:login"))
        self.assertContains(res_dash1_invalid, "Votre session a été fermée")

        # 4. Device 2 is still authenticated and works fine
        res_dash2 = client2.get(reverse("accounts:dashboard"))
        self.assertEqual(res_dash2.status_code, 200)


class AutomatedForgotPasswordFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = User.objects.create_user(
            username="sophia@univ.edu",
            email="sophia@univ.edu",
            password="AncienMotDePasse123!",
            first_name="Sophia",
            last_name="Lokossou"
        )

    def test_forgot_password_get_page(self):
        """Vérifie l'affichage de la page mot de passe oublié avec pré-remplissage."""
        res = self.client.get(reverse("accounts:forgot_password") + "?email=sophia@univ.edu")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Mot de passe oublié ?")
        self.assertContains(res, "sophia@univ.edu")
        self.assertContains(res, "Instantané & 100% Automatisé")

    def test_forgot_password_post_success_and_email_dispatched(self):
        """Vérifie que l'étudiant reçoit immédiatement un mot de passe temporaire par email."""
        from django.core import mail
        import re

        mail.outbox.clear()
        res = self.client.post(reverse("accounts:forgot_password"), {
            "identifier": "sophia@univ.edu"
        }, follow=False)

        # Doit rediriger vers la page de connexion avec pré-remplissage
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("accounts:login"), res.url)

        # Vérification en base de données
        self.student.refresh_from_db()
        self.assertTrue(self.student.must_change_password)
        self.assertFalse(self.student.check_password("AncienMotDePasse123!"))

        # Vérification de l'envoi de l'e-mail
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn("Réinitialisation de votre mot de passe", sent_email.subject)
        self.assertIn(self.student.email, sent_email.to)

        # Extraction du mot de passe temporaire
        match = re.search(r"ArchivEx-\d{4}", sent_email.body)
        self.assertIsNotNone(match)
        temp_pwd = match.group(0)
        self.assertTrue(self.student.check_password(temp_pwd))

    def test_forgot_password_full_lifecycle_with_forced_change(self):
        """
        Cycle de vie complet :
        1. Demande de mot de passe oublié
        2. Consultation du mot de passe temporaire dans la boîte de réception
        3. Connexion sur /connexion/
        4. Interception immédiate par le système obligeant à changer le mot de passe
        5. Définition du mot de passe personnel définitif
        6. L'ancien mot de passe temporaire est désormais inutilisable.
        """
        from django.core import mail
        import re

        # 1. Demande mot de passe oublié
        mail.outbox.clear()
        self.client.post(reverse("accounts:forgot_password"), {"identifier": "sophia@univ.edu"})
        self.student.refresh_from_db()
        self.assertTrue(self.student.must_change_password)

        temp_pwd = re.search(r"ArchivEx-\d{4}", mail.outbox[0].body).group(0)

        # 2. Tentative de connexion avec le mot de passe temporaire reçu par email
        login_res = self.client.post(reverse("accounts:login"), {
            "username": "sophia@univ.edu",
            "password": temp_pwd
        }, follow=False)

        # Le système redirige immédiatement vers la sécurisation obligatoire
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res.url, reverse("accounts:force_password_change"))

        # 3. Tentative de contourner en allant sur le profil ou tableau de bord -> bloqué par le middleware
        bypass_res = self.client.get(reverse("accounts:dashboard"), follow=False)
        self.assertEqual(bypass_res.status_code, 302)
        self.assertEqual(bypass_res.url, reverse("accounts:force_password_change"))

        # 4. L'étudiant enregistre son propre mot de passe personnel
        mon_nouveau_mot_de_passe = "MonSecretPersonnel2026@"
        change_res = self.client.post(reverse("accounts:force_password_change"), {
            "new_password1": mon_nouveau_mot_de_passe,
            "new_password2": mon_nouveau_mot_de_passe,
        }, follow=False)

        self.assertEqual(change_res.status_code, 302)

        # 5. Le compte est sécurisé et le flag must_change_password est levé
        self.student.refresh_from_db()
        self.assertFalse(self.student.must_change_password)
        self.assertTrue(self.student.check_password(mon_nouveau_mot_de_passe))
        self.assertFalse(self.student.check_password(temp_pwd), "Le mot de passe temporaire ne doit plus fonctionner")

    def test_two_device_locking_and_replacement(self):
        """
        Vérifie le verrouillage strict à 2 appareils :
        1. Connexion sur l'appareil 1 -> autorisé (1/2)
        2. Connexion sur l'appareil 2 -> autorisé (2/2)
        3. Connexion sur l'appareil 3 -> bloqué et redirigé vers limite d'appareils
        4. Remplacement de l'appareil 1 par l'appareil 3 -> autorisé et ancien révoqué.
        """
        from accounts.models import UserDevice

        student = User.objects.create_user(
            username="device_test_student",
            email="device@univ.edu",
            password="Password123!"
        )

        # 1. Appareil 1 (Smartphone)
        client1 = Client()
        client1.cookies["ax_device_id"] = "device_id_phone_111"
        res1 = client1.post(reverse("accounts:login"), {
            "username": "device@univ.edu",
            "password": "Password123!",
        }, follow=False)
        self.assertEqual(res1.status_code, 302)
        self.assertEqual(student.devices.count(), 1)
        self.assertTrue(student.devices.filter(device_id="device_id_phone_111").exists())

        # 2. Appareil 2 (PC portable)
        client2 = Client()
        client2.cookies["ax_device_id"] = "device_id_laptop_222"
        res2 = client2.post(reverse("accounts:login"), {
            "username": "device@univ.edu",
            "password": "Password123!",
        }, follow=False)
        self.assertEqual(res2.status_code, 302)
        self.assertEqual(student.devices.count(), 2)
        self.assertTrue(student.devices.filter(device_id="device_id_laptop_222").exists())

        # 3. Appareil 3 (tentative de connexion sur un 3e appareil)
        client3 = Client()
        client3.cookies["ax_device_id"] = "device_id_friend_333"
        res3 = client3.post(reverse("accounts:login"), {
            "username": "device@univ.edu",
            "password": "Password123!",
        }, follow=False)
        # Redirigé vers la page de limite d'appareils !
        self.assertEqual(res3.status_code, 302)
        self.assertEqual(res3.url, reverse("accounts:device_limit"))
        # Le 3e appareil n'est pas encore enregistré
        self.assertEqual(student.devices.count(), 2)

        # 4. Remplacement : l'étudiant choisit de remplacer l'appareil 1
        replace_res = client3.post(reverse("accounts:device_limit"), {
            "replace_device_id": "device_id_phone_111",
        }, follow=False)
        self.assertEqual(replace_res.status_code, 302)

        # Vérification : l'appareil 1 a disparu, l'appareil 3 est maintenant actif
        self.assertEqual(student.devices.count(), 2)
        self.assertFalse(student.devices.filter(device_id="device_id_phone_111").exists())
        self.assertTrue(student.devices.filter(device_id="device_id_friend_333").exists())

    def test_daily_revocation_limit_blocks_after_two(self):
        """
        Vérifie le blocage automatique pendant 24h après 2 révocations dans la même journée :
        1. Révocation 1 -> Autorisée (1/2)
        2. Révocation 2 -> Autorisée (2/2)
        3. Révocation 3 -> Bloquée avec interdiction de remplacer pendant 24h !
        """
        from accounts.models import UserDevice
        from accounts.utils import check_revocation_limit_status

        student = User.objects.create_user(
            username="cooldown_student",
            email="cooldown@univ.edu",
            password="Password123!"
        )

        dev1 = UserDevice.objects.create(user=student, device_id="dev_1", device_name="Appareil 1")
        dev2 = UserDevice.objects.create(user=student, device_id="dev_2", device_name="Appareil 2")

        client = Client()
        client.force_login(student)

        # 1. Révocation 1 -> Autorisée
        can_rev, rem, cd = check_revocation_limit_status(student)
        self.assertTrue(can_rev)
        self.assertEqual(rem, 2)
        res1 = client.post(reverse("accounts:revoke_device", kwargs={"device_pk": dev1.pk}), follow=False)
        self.assertEqual(res1.status_code, 302)
        self.assertEqual(student.device_revocations.count(), 1)

        # 2. Révocation 2 -> Autorisée
        can_rev, rem, cd = check_revocation_limit_status(student)
        self.assertTrue(can_rev)
        self.assertEqual(rem, 1)
        res2 = client.post(reverse("accounts:revoke_device", kwargs={"device_pk": dev2.pk}), follow=False)
        self.assertEqual(res2.status_code, 302)
        self.assertEqual(student.device_revocations.count(), 2)

        # 3. Révocation 3 -> Doit être strictement BLOQUÉE pendant 24h
        dev3 = UserDevice.objects.create(user=student, device_id="dev_3", device_name="Appareil 3")
        can_rev, rem, cd = check_revocation_limit_status(student)
        self.assertFalse(can_rev)
        self.assertEqual(rem, 0)
        self.assertIsNotNone(cd)

        res3 = client.post(reverse("accounts:revoke_device", kwargs={"device_pk": dev3.pk}), follow=False)
        self.assertEqual(res3.status_code, 302)
        # dev3 ne doit PAS avoir été supprimé !
        self.assertTrue(student.devices.filter(device_id="dev_3").exists())
        self.assertEqual(student.device_revocations.count(), 2)


