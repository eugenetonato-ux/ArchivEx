import re
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from support.models import SupportRequest, SupportReply
from accounts.services import generate_temporary_password, send_password_reset_email

User = get_user_model()

class PasswordResetSupportTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser(
            username="admin_test",
            email="admin@archivex.com",
            password="adminpassword123"
        )
        self.student = User.objects.create_user(
            username="etudiant1",
            email="etudiant1@test.com",
            password="oldpassword123",
            first_name="Jean",
            last_name="Dupont"
        )

    def test_generate_temporary_password(self):
        pwd = generate_temporary_password()
        self.assertTrue(re.match(r"^ArchivEx-\d{4}$", pwd), f"Password format mismatch: {pwd}")

    def test_send_password_reset_email(self):
        temp_pwd = generate_temporary_password()
        sent = send_password_reset_email(self.student, temp_pwd, admin_user=self.admin)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Réinitialisation de votre mot de passe", email.subject)
        self.assertIn(self.student.email, email.to)
        self.assertIn(temp_pwd, email.body)
        self.assertIn(self.student.username, email.body)

    def test_support_create_get_prefill(self):
        url = reverse("support:create") + "?category=recuperation_mot_de_passe&email=test@example.com"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial.get("category"), "recuperation_mot_de_passe")
        self.assertEqual(form.initial.get("guest_email"), "test@example.com")

    def test_support_create_links_existing_user_by_email(self):
        post_data = {
            "guest_name": "Jean Dupont",
            "guest_email": "etudiant1@test.com",
            "category": "recuperation_mot_de_passe",
            "message": "Bonjour, je ne retrouve plus mon mot de passe.",
        }
        response = self.client.post(reverse("support:create"), data=post_data)
        self.assertEqual(response.status_code, 302)
        ticket = SupportRequest.objects.filter(guest_email="etudiant1@test.com").latest("created_at")
        self.assertEqual(ticket.user, self.student)

    def test_admin_reset_temporary_password_action(self):
        ticket = SupportRequest.objects.create(
            user=self.student,
            guest_name=self.student.get_full_name(),
            guest_email=self.student.email,
            category="recuperation_mot_de_passe",
            message="Je n'arrive plus à me connecter."
        )

        self.client.force_login(self.admin)
        url = reverse("contributors:admin_support_detail", kwargs={"pk": ticket.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("target_student"), self.student)

        # Trigger reset
        post_response = self.client.post(url, data={"action": "reset_temp_password"}, follow=True)
        self.assertEqual(post_response.status_code, 200)

        # Ticket status updated
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "repondu")

        # Support reply created
        replies = SupportReply.objects.filter(request=ticket)
        self.assertTrue(replies.exists())
        reply = replies.first()
        self.assertEqual(reply.admin_user, self.admin)
        self.assertIn("ArchivEx-", reply.message)

        # Email sent
        self.assertTrue(len(mail.outbox) >= 1)
        reset_email = [m for m in mail.outbox if "Réinitialisation de votre mot de passe" in m.subject][0]
        self.assertIn(self.student.email, reset_email.to)

        # User's password was really updated
        self.student.refresh_from_db()
        self.assertFalse(self.student.check_password("oldpassword123"))

        # Extract generated pwd from reply or session
        match = re.search(r"ArchivEx-\d{4}", reply.message)
        self.assertIsNotNone(match)
        temp_pwd = match.group(0)
        self.assertTrue(self.student.check_password(temp_pwd))
        self.assertTrue(self.student.must_change_password)

    def test_student_login_with_temp_password_forces_change(self):
        # Set temp password and must_change_password flag
        temp_pwd = generate_temporary_password()
        self.student.set_password(temp_pwd)
        self.student.must_change_password = True
        self.student.save()

        # 1. Login with temporary password
        login_url = reverse("accounts:login")
        login_res = self.client.post(login_url, {
            "username": self.student.username,
            "password": temp_pwd,
        }, follow=False)

        # Must be redirected to forced password change
        self.assertEqual(login_res.status_code, 302)
        self.assertIn(reverse("accounts:force_password_change"), login_res.url)

        # Follow redirect
        res = self.client.get(login_res.url)
        self.assertEqual(res.status_code, 200)
        self.assertIn("Définissez votre mot de passe", res.content.decode("utf-8"))

        # 2. Try to bypass by going to dashboard directly -> Middleware intercepts!
        dash_res = self.client.get(reverse("accounts:dashboard"), follow=False)
        self.assertEqual(dash_res.status_code, 302)
        self.assertEqual(dash_res.url, reverse("accounts:force_password_change"))

        # 3. Submit new personal password
        new_pwd = "MonNouveauSuperMotDePasse2026!"
        change_res = self.client.post(reverse("accounts:force_password_change"), {
            "new_password1": new_pwd,
            "new_password2": new_pwd,
        }, follow=True)

        self.assertEqual(change_res.status_code, 200)

        # 4. Check user status in DB
        self.student.refresh_from_db()
        self.assertFalse(self.student.must_change_password)
        self.assertTrue(self.student.check_password(new_pwd))
        self.assertFalse(self.student.check_password(temp_pwd), "Temporary password must no longer work!")

        # 5. Dashboard is now accessible freely
        dash_res_after = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(dash_res_after.status_code, 200)

