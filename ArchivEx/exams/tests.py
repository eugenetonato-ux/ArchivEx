from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from exams.models import Exam
from payments.models import SemesterAccess

User = get_user_model()


class ArchivExFlowTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="L1")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique de Gestion")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")
        
        self.subject = Subject.objects.create(semester=self.semester, name="Algorithmique", is_free=False)
        
        self.exam_free = Exam.objects.create(
            title="Épreuve Gratuite Algo",
            subject=self.subject,
            semester=self.semester,
            filiere=self.filiere,
            level=self.level,
            academic_year=self.year,
            exam_type="examen",
            year=2024,
            is_free=True,
            is_published=True,
            file=ContentFile(b"%PDF-1.4 ... demo pdf ...", name="algo_free.pdf")
        )

        self.exam_premium = Exam.objects.create(
            title="Épreuve Premium SQL",
            subject=self.subject,
            semester=self.semester,
            filiere=self.filiere,
            level=self.level,
            academic_year=self.year,
            exam_type="devoir",
            year=2024,
            is_free=False,
            is_published=True,
            file=ContentFile(b"%PDF-1.4 ... premium sql ...", name="sql_premium.pdf")
        )

        self.student = User.objects.create_user(
            username="student@univ.edu",
            email="student@univ.edu",
            password="Password123!"
        )

    def test_public_pages(self):
        response = self.client.get(reverse("academics:home"))
        self.assertEqual(response.status_code, 200)

        self.client.login(username="student@univ.edu", password="Password123!")
        response = self.client.get(reverse("academics:filieres"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse("exams:liste"))
        self.assertEqual(response.status_code, 200)

    def test_free_exam_pdf_streaming(self):
        self.client.login(username="student@univ.edu", password="Password123!")
        url = reverse("exams:stream_pdf", kwargs={"pk": self.exam_free.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_premium_exam_access_denied_without_pass(self):
        self.client.login(username="student@univ.edu", password="Password123!")
        url = reverse("exams:stream_pdf", kwargs={"pk": self.exam_premium.id})
        response = self.client.get(url)
        # Should redirect to pass_semestre page
        self.assertRedirects(response, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))


    def test_premium_exam_access_granted_with_active_pass(self):
        # Activate pass for student
        SemesterAccess.objects.create(
            user=self.student,
            school=self.school,
            level=self.level,
            filiere=self.filiere,
            academic_year=self.year,
            semester=self.semester,
            activated_at=timezone.now()
        )
        self.client.login(username="student@univ.edu", password="Password123!")
        
        url = reverse("exams:stream_pdf", kwargs={"pk": self.exam_premium.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
