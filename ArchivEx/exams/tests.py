from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from exams.models import Exam
from payments.models import SemesterAccess
from subscriptions.services import can_user_access

User = get_user_model()



def make_valid_pdf_content(title="Sample PDF"):
    from io import BytesIO
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.drawString(100, 800, title)
    c.showPage()
    c.save()
    return buf.getvalue()


class ArchivExFlowTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school = School.objects.create(name="ENEAM", slug="eneam", is_active=True)
        self.level = Level.objects.create(name="L1")
        self.filiere = Filiere.objects.create(school=self.school, level=self.level, name="Informatique de Gestion")
        self.year = AcademicYear.objects.create(label="2025-2026")
        self.semester = Semester.objects.create(filiere=self.filiere, academic_year=self.year, label="Semestre 1")
        
        self.subject = Subject.objects.create(semester=self.semester, name="Algorithmique", is_free=False)
        
        pdf_data = make_valid_pdf_content("Test PDF Document")

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
            file=ContentFile(pdf_data, name="algo_free.pdf"),
            correction_file=ContentFile(pdf_data, name="algo_free_corr.pdf"),
            summary_file=ContentFile(pdf_data, name="algo_free_sum.pdf"),
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
            file=ContentFile(pdf_data, name="sql_premium.pdf"),
            correction_file=ContentFile(pdf_data, name="sql_prem_corr.pdf"),
            summary_file=ContentFile(pdf_data, name="sql_prem_sum.pdf"),
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

    def test_v2_summaries_guides_and_notifications(self):
        from content.models import Summary, Guide
        from subscriptions.models import UserSubscription
        from contributors.models import ContributorProfile
        from contributors.permissions import check_school_permission
        from notifications.services import notify_target_students

        # 1. Summary creation & access
        summary = Summary.objects.create(
            title="Résumé de Maths",
            subject=self.subject,
            content="Contenu résumé de maths...",
            access_type="PREMIUM",
            publication_status="PUBLISHED"
        )
        self.client.login(username="student@univ.edu", password="Password123!")

        # Unsubscribed student -> Paywall active
        res = self.client.get(reverse("content:summary_detail", kwargs={"pk": summary.id}))
        self.assertFalse(res.context["has_access"])

        # Grant Subscription -> Access allowed
        UserSubscription.objects.create(
            user=self.student,
            semester=self.semester,
            filiere=self.filiere,
            school=self.school,
            is_active=True
        )
        res = self.client.get(reverse("content:summary_detail", kwargs={"pk": summary.id}))
        self.assertTrue(res.context["has_access"])


        # 2. Contributor School Permission check
        school_b = School.objects.create(name="FLASH", slug="flash", is_active=True)
        contrib_user = User.objects.create_user(username="contrib@univ.edu", password="Password123!")
        contrib_prof = ContributorProfile.objects.create(
            user=contrib_user,
            role="SCHOOL_CONTENT_MANAGER",
            is_active=True
        )
        contrib_prof.assigned_schools.add(self.school)

        # 4. Phase 14 Access Control & Security Tests
        self.exam_free.correction_file = ContentFile(b"%PDF-1.4 ... correction free exam ...", name="corr_free_exam.pdf")
        self.exam_free.summary_file = ContentFile(b"%PDF-1.4 ... summary free exam ...", name="sum_free_exam.pdf")
        self.exam_free.save()

        self.exam_premium.correction_file = ContentFile(b"%PDF-1.4 ... correction premium exam ...", name="corr_premium_exam.pdf")
        self.exam_premium.summary_file = ContentFile(b"%PDF-1.4 ... summary premium exam ...", name="sum_premium_exam.pdf")
        self.exam_premium.save()

    def test_free_exam_correction_and_summary_remain_premium(self):
        """Even for a FREE exam, correction and summary PDFs are ALWAYS PREMIUM (blocked without Pass)."""
        self.client.login(username="student@univ.edu", password="Password123!")

        # Free exam PDF is accessible
        url_exam = reverse("exams:stream_pdf", kwargs={"pk": self.exam_free.id})
        res_exam = self.client.get(url_exam)
        self.assertEqual(res_exam.status_code, 200)

        # Free exam correction PDF requires Pass
        url_corr = reverse("exams:stream_correction_pdf", kwargs={"pk": self.exam_free.id})
        res_corr = self.client.get(url_corr)
        self.assertRedirects(res_corr, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))

        # Free exam summary PDF requires Pass
        url_sum = reverse("exams:stream_summary_pdf", kwargs={"pk": self.exam_free.id})
        res_sum = self.client.get(url_sum)
        self.assertRedirects(res_sum, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))

    def test_premium_correction_and_summary_accessible_with_pass(self):
        """With active Pass, student can access exam, correction, and summary PDFs."""
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

        url_corr = reverse("exams:stream_correction_pdf", kwargs={"pk": self.exam_free.id})
        res_corr = self.client.get(url_corr)
        self.assertEqual(res_corr.status_code, 200)

        url_sum = reverse("exams:stream_summary_pdf", kwargs={"pk": self.exam_free.id})
        res_sum = self.client.get(url_sum)
        self.assertEqual(res_sum.status_code, 200)

    def test_free_catalog_mode(self):
        """Free catalog view returns only free exams."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res = self.client.get(reverse("exams:free_liste"))
        self.assertEqual(res.status_code, 200)
        exams = list(res.context["exams"])
        self.assertIn(self.exam_free, exams)
        self.assertNotIn(self.exam_premium, exams)

    def test_draft_exam_exclusion_and_idor_protection(self):
        """Unpublished draft exams are excluded from public catalog and return 404 for non-staff."""
        draft_exam = Exam.objects.create(
            title="Brouillon Confidentiel",
            subject=self.subject,
            semester=self.semester,
            filiere=self.filiere,
            level=self.level,
            academic_year=self.year,
            exam_type="examen",
            year=2024,
            is_published=False,
            file=ContentFile(b"%PDF-1.4 ... draft ...", name="draft.pdf")
        )
        self.client.login(username="student@univ.edu", password="Password123!")

        res_list = self.client.get(reverse("exams:liste"))
        self.assertNotIn(draft_exam, list(res_list.context["exams"]))

        res_detail = self.client.get(reverse("exams:detail", kwargs={"pk": draft_exam.id}))
        self.assertEqual(res_detail.status_code, 404)

        res_pdf = self.client.get(reverse("exams:stream_pdf", kwargs={"pk": draft_exam.id}))
        self.assertEqual(res_pdf.status_code, 404)

    def test_protected_student_viewer_and_watermark_stream(self):
        """Student with Pass can access viewer and stream watermarked PDF containing student info."""
        SemesterAccess.objects.create(
            user=self.student,
            school=self.school,
            level=self.level,
            filiere=self.filiere,
            academic_year=self.year,
            semester=self.semester,
            activated_at=timezone.now()
        )
        self.student.first_name = "Jean"
        self.student.last_name = "Dupont"
        self.student.save()

        self.client.login(username="student@univ.edu", password="Password123!")

        # Viewer page
        url_viewer = reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=exam"
        res_viewer = self.client.get(url_viewer)
        self.assertEqual(res_viewer.status_code, 200)

        # Stream watermarked PDF
        url_stream = reverse("exams:stream_watermarked_pdf", kwargs={"pk": self.exam_premium.id}) + "?type=exam"
        res_stream = self.client.get(url_stream)
        self.assertEqual(res_stream.status_code, 200)
        self.assertEqual(res_stream["Content-Type"], "application/pdf")
        stream_bytes = b"".join(res_stream.streaming_content)
        self.assertGreater(len(stream_bytes), 100)

    def test_student_viewer_denied_without_pass(self):
        """Student without Pass is denied access to premium resources in viewer."""
        self.client.login(username="student@univ.edu", password="Password123!")
        url_viewer = reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=exam"
        res = self.client.get(url_viewer)
        self.assertRedirects(res, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))




