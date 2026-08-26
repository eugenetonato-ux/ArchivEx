from django.urls import path
from . import views

app_name = "academics"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("recherche/", views.global_search_view, name="global_search"),
    path("a-propos/", views.about_view, name="about"),
    path("filieres/", views.filiere_list_view, name="filieres"),
    path("filieres/<int:filiere_id>/semestres/", views.semester_list_view, name="semestres"),
    path("semestres/<int:semester_id>/matieres/", views.subject_list_view, name="matieres"),
    path("403/", views.custom_403_view, name="error_403"),
    path("404/", views.custom_404_view, name="error_404"),
    path("500/", views.custom_500_view, name="error_500"),
]


