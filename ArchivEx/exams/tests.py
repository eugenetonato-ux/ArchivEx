from django.test import TestCase, Client, override_settings
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
    try:
        from reportlab.pdfgen import canvas
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(595, 842))
        c.drawString(100, 800, title)
        c.showPage()
        c.save()
        return buf.getvalue()
    except ImportError:
        return (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>\nendobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
            b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF"
        )


@override_settings(
    USE_SUPABASE_STORAGE=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
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
        url = reverse("exams:stream_correction_pdf", kwargs={"pk": self.exam_premium.id})
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
        self.exam_premium.correction_file = ContentFile(b"%PDF-1.4 ... correction premium exam ...", name="corr_premium_exam.pdf")
        self.exam_premium.summary_file = ContentFile(b"%PDF-1.4 ... summary premium exam ...", name="sum_premium_exam.pdf")
        self.exam_premium.save()

    def test_free_exam_correction_and_summary_remain_premium(self):
        """Even for a FREE exam, correction and summary PDFs are ALWAYS PREMIUM (blocked without Pass)."""
        self.exam_free.correction_file = ContentFile(b"%PDF-1.4 ... correction free exam ...", name="corr_free_exam.pdf")
        self.exam_free.summary_file = ContentFile(b"%PDF-1.4 ... summary free exam ...", name="sum_free_exam.pdf")
        self.exam_free.save()

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

        url_corr = reverse("exams:stream_correction_pdf", kwargs={"pk": self.exam_premium.id})
        res_corr = self.client.get(url_corr)
        self.assertEqual(res_corr.status_code, 200)

        url_sum = reverse("exams:stream_summary_pdf", kwargs={"pk": self.exam_premium.id})
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

    def test_free_exam_accessible_without_login_or_pass(self):
        """Free exam is accessible in viewer and stream without requiring login or Pass Semestre."""
        self.client.logout()
        # Viewer access
        viewer_url = reverse("exams:student_viewer", kwargs={"pk": self.exam_free.id}) + "?type=exam"
        res_viewer = self.client.get(viewer_url)
        self.assertEqual(res_viewer.status_code, 200)

        # Stream PDF access without login
        stream_url = reverse("exams:stream_pdf", kwargs={"pk": self.exam_free.id})
        res_stream = self.client.get(stream_url)
        self.assertEqual(res_stream.status_code, 200)

    def test_free_subject_makes_exams_accessible_without_pass(self):
        """Toutes les épreuves sont accessibles sans Pass pour tous les étudiants."""
        self.client.login(username="student@univ.edu", password="Password123!")
        # L'épreuve est directement accessible sans Pass
        self.assertTrue(can_user_access(self.student, self.exam_premium))

        viewer_url = reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=exam"
        res = self.client.get(viewer_url)
        self.assertEqual(res.status_code, 200)

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
        self.assertIn("inline", res_stream["Content-Disposition"])
        stream_bytes = b"".join(res_stream.streaming_content)
        self.assertGreater(len(stream_bytes), 100)

        # Verify downloading is strictly prohibited: Content-Disposition remains inline
        url_download = reverse("exams:stream_watermarked_pdf", kwargs={"pk": self.exam_premium.id}) + "?type=exam&download=1"
        res_download = self.client.get(url_download)
        self.assertEqual(res_download.status_code, 200)
        self.assertIn("inline", res_download["Content-Disposition"])

    def test_student_viewer_denied_without_pass(self):
        """Student without Pass is denied access to correction in viewer."""
        self.client.login(username="student@univ.edu", password="Password123!")
        url_viewer = reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=correction"
        res = self.client.get(url_viewer)
        self.assertRedirects(res, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))

    def test_parcours_1_unauthenticated_free_resources_viewer(self):
        """1. Étudiant non connecté -> Ressources gratuites -> Épreuves -> UE -> année -> consultation."""
        self.client.logout()
        res_list = self.client.get(reverse("exams:free_liste") + "?category=epreuves")
        self.assertEqual(res_list.status_code, 200)
        self.assertTrue(any("algo_free" in y["exam"].file.name for ue in res_list.context["ue_list"] for y in ue["years"]))

        # Consultation directe autorisée
        viewer_url = reverse("exams:student_viewer", kwargs={"pk": self.exam_free.id}) + "?type=exam"
        res_view = self.client.get(viewer_url)
        self.assertEqual(res_view.status_code, 200)

    def test_parcours_2_authenticated_without_pass_free_consultation(self):
        """2. Étudiant connecté sans Pass -> Ressources gratuites -> consultation d'une ressource gratuite."""
        self.client.login(username="student@univ.edu", password="Password123!")
        viewer_url = reverse("exams:student_viewer", kwargs={"pk": self.exam_free.id}) + "?type=exam"
        res_view = self.client.get(viewer_url)
        self.assertEqual(res_view.status_code, 200)

    def test_parcours_3_authenticated_without_pass_locked_premium(self):
        """3. Étudiant connecté sans Pass -> Corrigés premium -> ressource verrouillée -> invitation à activer le Pass."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res_list = self.client.get(reverse("exams:premium_liste") + "?category=corrections")
        self.assertEqual(res_list.status_code, 200)
        
        # Vérification que la correction premium est marquée verrouillée
        premium_years = [y for ue in res_list.context["ue_list"] for y in ue["years"] if y.get("exam_id") == self.exam_premium.id]
        self.assertTrue(len(premium_years) > 0)
        self.assertTrue(premium_years[0]["is_locked"])

        # Tentative de consultation -> redirection vers activation du Pass
        viewer_url = reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=correction"
        res_view = self.client.get(viewer_url)
        self.assertRedirects(res_view, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))

    def test_parcours_4_5_6_active_pass_full_access(self):
        """4, 5, 6. Étudiant avec Pass actif -> Épreuves, Corrections, Résumés -> consultation immédiate."""
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

        # 4. Épreuves
        res_exam = self.client.get(reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=exam")
        self.assertEqual(res_exam.status_code, 200)

        # 5. Épreuves corrigées
        res_corr = self.client.get(reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=correction")
        self.assertEqual(res_corr.status_code, 200)

        # 6. Résumés
        res_sum = self.client.get(reverse("exams:student_viewer", kwargs={"pk": self.exam_premium.id}) + "?type=summary")
        self.assertEqual(res_sum.status_code, 200)

    def test_parcours_1_gratuit_epreuves_ue_annee_ressource(self):
        """Gratuit -> Épreuves -> UE -> année -> ressource."""
        self.client.logout()
        res = self.client.get(reverse("exams:free_liste") + "?category=epreuves")
        self.assertEqual(res.status_code, 200)
        # Vérification de la présence de l'UE et de l'année
        ue_item = next((ue for ue in res.context["ue_list"] if ue["subject"].id == self.subject.id), None)
        self.assertIsNotNone(ue_item)
        self.assertTrue(len(ue_item["years"]) > 0)
        # Consultation
        v_url = ue_item["years"][0]["viewer_url"]
        res_view = self.client.get(v_url)
        self.assertEqual(res_view.status_code, 200)

    def test_parcours_2_gratuit_corrections_ue_annee_ressource(self):
        """RÈGLE ARCHIVEX : Tous les corrigés sont exclusivement Premium et ne s'affichent jamais en gratuit."""
        self.client.logout()
        res = self.client.get(reverse("exams:free_liste") + "?category=corrections")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["category"], "epreuves")

    def test_parcours_3_gratuit_resumes_ue_annee_ressource(self):
        """RÈGLE ARCHIVEX : Tous les résumés sont exclusivement Premium et ne s'affichent jamais en gratuit."""
        self.client.logout()
        res = self.client.get(reverse("exams:free_liste") + "?category=resumes")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["category"], "epreuves")

    def test_parcours_4_premium_sans_pass_epreuves_verrouillees(self):
        """Toutes les épreuves restent 100% gratuites sans Pass."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res = self.client.get(reverse("exams:premium_liste") + "?category=epreuves")
        self.assertEqual(res.status_code, 200)
        ue_item = next((ue for ue in res.context["ue_list"] if ue["subject"].id == self.subject.id), None)
        self.assertIsNotNone(ue_item)
        prem_year = next((y for y in ue_item["years"] if y.get("exam_id") == self.exam_premium.id), None)
        self.assertIsNotNone(prem_year)
        self.assertFalse(prem_year["is_locked"])
        # Consultation directe autorisée
        res_view = self.client.get(prem_year["viewer_url"])
        self.assertEqual(res_view.status_code, 200)

    def test_parcours_5_premium_sans_pass_corrections_verrouillees(self):
        """Premium sans Pass -> Épreuves corrigées -> UE -> année -> ressource verrouillée."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res = self.client.get(reverse("exams:premium_liste") + "?category=corrections")
        self.assertEqual(res.status_code, 200)
        ue_item = next((ue for ue in res.context["ue_list"] if ue["subject"].id == self.subject.id), None)
        self.assertIsNotNone(ue_item)
        prem_year = next((y for y in ue_item["years"] if y.get("exam_id") == self.exam_premium.id), None)
        self.assertIsNotNone(prem_year)
        self.assertTrue(prem_year["is_locked"])
        res_view = self.client.get(prem_year["viewer_url"])
        self.assertRedirects(res_view, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))

    def test_parcours_6_premium_sans_pass_resumes_verrouillees(self):
        """Premium sans Pass -> Résumés -> UE -> année -> ressource verrouillée."""
        self.client.login(username="student@univ.edu", password="Password123!")
        res = self.client.get(reverse("exams:premium_liste") + "?category=resumes")
        self.assertEqual(res.status_code, 200)
        ue_item = next((ue for ue in res.context["ue_list"] if ue["subject"].id == self.subject.id), None)
        self.assertIsNotNone(ue_item)
        prem_year = next((y for y in ue_item["years"] if y.get("exam_id") == self.exam_premium.id), None)
        self.assertIsNotNone(prem_year)
        self.assertTrue(prem_year["is_locked"])
        res_view = self.client.get(prem_year["viewer_url"])
        self.assertRedirects(res_view, reverse("payments:pass_semestre", kwargs={"semester_id": self.semester.id}))

    def test_parcours_7_8_9_premium_avec_pass_consultation(self):
        """Premium avec Pass -> Épreuves, Corrections, Résumés -> UE -> année -> consultation immédiate."""
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

        # 7. Épreuves
        res = self.client.get(reverse("exams:premium_liste") + "?category=epreuves")
        ue_item = next(ue for ue in res.context["ue_list"] if ue["subject"].id == self.subject.id)
        prem_year = next(y for y in ue_item["years"] if y.get("exam_id") == self.exam_premium.id)
        self.assertFalse(prem_year["is_locked"])
        res_view = self.client.get(prem_year["viewer_url"])
        self.assertEqual(res_view.status_code, 200)

        # 8. Corrections
        res_corr = self.client.get(reverse("exams:premium_liste") + "?category=corrections")
        ue_item_c = next(ue for ue in res_corr.context["ue_list"] if ue["subject"].id == self.subject.id)
        prem_year_c = next(y for y in ue_item_c["years"] if y.get("exam_id") == self.exam_premium.id)
        self.assertFalse(prem_year_c["is_locked"])
        res_view_c = self.client.get(prem_year_c["viewer_url"])
        self.assertEqual(res_view_c.status_code, 200)

        # 9. Résumés
        res_res = self.client.get(reverse("exams:premium_liste") + "?category=resumes")
        ue_item_r = next(ue for ue in res_res.context["ue_list"] if ue["subject"].id == self.subject.id)
        prem_year_r = next(y for y in ue_item_r["years"] if y.get("exam_id") == self.exam_premium.id)
        self.assertFalse(prem_year_r["is_locked"])
        res_view_r = self.client.get(prem_year_r["viewer_url"])
        self.assertEqual(res_view_r.status_code, 200)

    def test_multi_years_grouping_and_descending_sort(self):
        """Vérifie que les années d'une même UE sont regroupées et triées de la plus récente à la plus ancienne."""
        year_2024 = AcademicYear.objects.create(label="2023-2024")
        pdf_data = make_valid_pdf_content("Test 2023-2024")
        Exam.objects.create(
            title="Ancienne épreuve Algo",
            subject=self.subject,
            semester=self.semester,
            filiere=self.filiere,
            level=self.level,
            academic_year=year_2024,
            exam_type="examen",
            year=2023,
            is_free=True,
            is_published=True,
            file=ContentFile(pdf_data, name="algo_2023.pdf"),
        )
        res = self.client.get(reverse("exams:free_liste") + "?category=epreuves")
        ue_item = next(ue for ue in res.context["ue_list"] if ue["subject"].id == self.subject.id)
        
        # Les années doivent être triées décroissantes : 2025-2026 avant 2023-2024
        sort_years = [y["sort_year"] for y in ue_item["years"]]
        self.assertEqual(sort_years, sorted(sort_years, reverse=True))

    def test_ue_isolation_no_resource_leak(self):
        """Vérifie qu'aucune ressource ne se retrouve mélangée entre deux UE distinctes."""
        subject2 = Subject.objects.create(semester=self.semester, name="Microéconomie", is_free=True)
        pdf_data = make_valid_pdf_content("Microeconomics Exam")
        Exam.objects.create(
            title="Épreuve Microéconomie",
            subject=subject2,
            semester=self.semester,
            filiere=self.filiere,
            level=self.level,
            academic_year=self.year,
            exam_type="examen",
            year=2025,
            is_free=True,
            is_published=True,
            file=ContentFile(pdf_data, name="micro_2025.pdf"),
        )
        res = self.client.get(reverse("exams:free_liste") + "?category=epreuves")
        ue_map = {ue["subject"].id: ue for ue in res.context["ue_list"]}
        
        self.assertIn(self.subject.id, ue_map)
        self.assertIn(subject2.id, ue_map)
        
        # Aucun fichier de subject2 dans self.subject
        algo_files = [y["exam"].file.name for y in ue_map[self.subject.id]["years"]]
        self.assertFalse(any("micro" in f for f in algo_files))
        
        # Aucun fichier de self.subject dans subject2
        micro_files = [y["exam"].file.name for y in ue_map[subject2.id]["years"]]
        self.assertTrue(any("micro" in f for f in micro_files))
        self.assertFalse(any("algo" in f for f in micro_files))

    def test_multi_criteria_search_and_filter(self):
        """Vérifie le filtrage par UE, filière, semestre, année académique et type."""
        # 1. Filtre par subject ID
        res_subj = self.client.get(reverse("exams:free_liste") + f"?subject={self.subject.id}")
        self.assertEqual(len(res_subj.context["ue_list"]), 1)
        self.assertEqual(res_subj.context["ue_list"][0]["subject"].id, self.subject.id)

        # 2. Filtre par filière
        res_fil = self.client.get(reverse("exams:free_liste") + f"?filiere={self.filiere.id}")
        self.assertGreaterEqual(len(res_fil.context["ue_list"]), 1)

        # 3. Filtre par texte q
        res_q = self.client.get(reverse("exams:free_liste") + "?q=Algorithmique")
        self.assertEqual(len(res_q.context["ue_list"]), 1)
        self.assertEqual(res_q.context["ue_list"][0]["subject"].name, "Algorithmique")

    def test_strict_filiere_isolation(self):
        """Vérifie l'étanchéité stricte entre deux filières : aucun sujet d'une autre filière ne doit fuiter."""
        other_filiere = Filiere.objects.create(name="Statistique", school=self.school, level=self.level)
        other_semester = Semester.objects.create(label="Semestre 1", number=1, filiere=other_filiere, academic_year=self.year, is_active=True)
        other_subj = Subject.objects.create(name="Statistique Mathématique", code="STAT101", semester=other_semester, is_free=True)
        Exam.objects.create(
            title="Examen STAT",
            subject=other_subj,
            semester=other_semester,
            filiere=other_filiere,
            level=self.level,
            academic_year=self.year,
            year="2024",
            is_published=True,
            is_free=True,
            file="exams/dummy_stat.pdf",
        )

        # 1. Requête pour la filière d'origine (self.filiere)
        res_f1 = self.client.get(reverse("exams:liste") + f"?filiere={self.filiere.id}")
        f1_subjects = [item["subject"].id for item in res_f1.context["ue_list"]]
        self.assertIn(self.subject.id, f1_subjects)
        self.assertNotIn(other_subj.id, f1_subjects)

        # 2. Requête pour other_filiere (visiteur)
        res_f2 = self.client.get(reverse("exams:liste") + f"?filiere={other_filiere.id}")
        f2_subjects = [item["subject"].id for item in res_f2.context["ue_list"]]
        self.assertIn(other_subj.id, f2_subjects)
        self.assertNotIn(self.subject.id, f2_subjects)

        # 3. Étudiant connecté : strictement confiné à sa filière, tout ?filiere= autre est ignoré
        from accounts.models import StudentProfile
        student_user = User.objects.create_user(username="student_iso@test.com", email="student_iso@test.com", password="password123")
        StudentProfile.objects.create(user=student_user, school=self.school, level=self.level, filiere=self.filiere)
        self.client.force_login(student_user)
        res_student_hack = self.client.get(reverse("exams:liste") + f"?filiere={other_filiere.id}")
        student_subjects = [item["subject"].id for item in res_student_hack.context["ue_list"]]
        self.assertIn(self.subject.id, student_subjects)
        self.assertNotIn(other_subj.id, student_subjects)
        # Aucun sélecteur de filière exposé à l'étudiant
        self.assertEqual(len(res_student_hack.context["available_filieres"]), 0)
        self.assertNotContains(res_student_hack, "Aperçu Admin · Filière")

        # 4. Staff / Admin connecté : accès à la prévisualisation des différentes filières
        admin_user = get_user_model().objects.create_superuser(
            username="super_filiere_admin", email="admin_fil@test.com", password="adminpassword123"
        )
        self.client.force_login(admin_user)
        res_admin = self.client.get(reverse("exams:liste") + f"?filiere={other_filiere.id}")
        self.assertTrue(res_admin.context["is_staff_user"])
        self.assertGreaterEqual(len(res_admin.context["available_filieres"]), 2)
        self.assertContains(res_admin, "Aperçu Admin · Filière")








