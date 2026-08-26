from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere
from accounts.models import StudentProfile
from notifications.models import Notification
from notifications.services import notify_target_students

User = get_user_model()


class NotificationEngineTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school_eneam = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_flash = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)

        self.level_l1 = Level.objects.create(name="Licence 1", code="L1")

        self.filiere_eneam = Filiere.objects.create(school=self.school_eneam, level=self.level_l1, name="Informatique")
        self.filiere_flash = Filiere.objects.create(school=self.school_flash, level=self.level_l1, name="Lettres")

        # Student ENEAM
        self.student_eneam = User.objects.create_user(username="eneam_student@univ.edu", password="Password123!")
        StudentProfile.objects.create(user=self.student_eneam, school=self.school_eneam, level=self.level_l1, filiere=self.filiere_eneam)

        # Student FLASH
        self.student_flash = User.objects.create_user(username="flash_student@univ.edu", password="Password123!")
        StudentProfile.objects.create(user=self.student_flash, school=self.school_flash, level=self.level_l1, filiere=self.filiere_flash)

    def test_targeted_notification_delivery(self):
        """Notification for ENEAM reaches ENEAM student, but NOT FLASH student."""
        count = notify_target_students(
            school=self.school_eneam,
            notification_type="NEW_EXAM",
            title="Nouvelle épreuve ENEAM",
            message="Message pour ENEAM",
            link="/epreuves/"
        )
        self.assertEqual(count, 1)

        # Verify ENEAM student has 1 notification
        self.assertEqual(Notification.objects.filter(recipient=self.student_eneam).count(), 1)

        # Verify FLASH student has 0 notifications
        self.assertEqual(Notification.objects.filter(recipient=self.student_flash).count(), 0)

    def test_mark_notification_as_read(self):
        """Student can mark notification as read via URL endpoint."""
        notif = Notification.objects.create(
            recipient=self.student_eneam,
            notification_type="SYSTEM",
            title="Test",
            message="Msg",
            is_read=False
        )

        self.client.login(username="eneam_student@univ.edu", password="Password123!")
        res = self.client.get(reverse("notifications:mark_read", kwargs={"pk": notif.pk}))
        
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_read(self):
        """Student can mark all notifications as read."""
        Notification.objects.create(recipient=self.student_eneam, title="N1", message="M1")
        Notification.objects.create(recipient=self.student_eneam, title="N2", message="M2")

        self.client.login(username="eneam_student@univ.edu", password="Password123!")
        res = self.client.get(reverse("notifications:mark_all_read"))

        unread_count = Notification.objects.filter(recipient=self.student_eneam, is_read=False).count()
        self.assertEqual(unread_count, 0)
