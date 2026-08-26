from django.urls import path
from . import views

app_name = "academics"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("a-propos/", views.about_view, name="about"),
    path("filieres/", views.filiere_list_view, name="filieres"),
    path("filieres/<int:filiere_id>/semestres/", views.semester_list_view, name="semestres"),
    path("semestres/<int:semester_id>/matieres/", views.subject_list_view, name="matieres"),
]
