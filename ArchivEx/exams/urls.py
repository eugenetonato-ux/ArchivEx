from django.urls import path
from . import views

app_name = "exams"

urlpatterns = [
    path("", views.exam_list, name="liste"),
    path("<int:pk>/", views.exam_detail, name="detail"),
    path("<int:pk>/pdf/", views.stream_exam_pdf, name="stream_pdf"),
    path("<int:pk>/favori/", views.toggle_favorite, name="toggle_favorite"),
]