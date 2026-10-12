from django.urls import path
from . import views

app_name = "content"

urlpatterns = [
    path("guide-etudiant/", views.student_guide_view, name="student_guide"),
    path("resumes/", views.summary_list, name="summary_list"),
    path("resumes/<int:pk>/", views.summary_detail, name="summary_detail"),
    path("resumes/<int:pk>/viewer/", views.summary_viewer_view, name="summary_viewer"),
    path("resumes/<int:pk>/pdf/", views.stream_summary_pdf_view, name="stream_summary_pdf"),
    path("guides/", views.guide_list, name="guide_list"),
    path("guides/<int:pk>/", views.guide_detail, name="guide_detail"),
    path("conseils/", views.article_list, name="article_list"),
    path("conseils/<int:pk>/", views.article_detail, name="article_detail"),
]

