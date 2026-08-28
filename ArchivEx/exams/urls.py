from django.urls import path
from . import views

app_name = "exams"

urlpatterns = [
    path("", views.exam_list, name="liste"),
    path("gratuites/", views.exam_list, name="free_liste"),
    path("<int:pk>/", views.exam_detail, name="detail"),
    path("<int:pk>/pdf/", views.stream_exam_pdf, name="stream_pdf"),
    path("<int:pk>/correction-pdf/", views.stream_correction_pdf, name="stream_correction_pdf"),
    path("<int:pk>/summary-pdf/", views.stream_summary_pdf, name="stream_summary_pdf"),
    path("<int:pk>/viewer/", views.student_viewer_view, name="student_viewer"),
    path("<int:pk>/stream-watermarked/", views.stream_watermarked_pdf_view, name="stream_watermarked_pdf"),
    path("<int:pk>/favori/", views.toggle_favorite, name="toggle_favorite"),
]