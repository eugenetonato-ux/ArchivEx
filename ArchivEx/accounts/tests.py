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


