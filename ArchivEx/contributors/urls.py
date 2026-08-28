from django.urls import path
from . import views

app_name = "contributors"

urlpatterns = [
    path("login/", views.admin_login_view, name="admin_login"),
    path("logout/", views.admin_logout_view, name="admin_logout"),
    path("api/filieres/", views.get_filieres_by_school_api, name="api_filieres"),
    path("", views.admin_dashboard_view, name="admin_dashboard"),
    path("contexte/", views.set_context_view, name="set_context"),

    # Épreuves & Bibliothèque
    path("library/", views.library_index_view, name="library_index"),
    path("library/<int:pk>/", views.library_exam_detail_view, name="library_detail"),
    path("library/<int:pk>/download-original/<str:file_type>/", views.library_download_original_view, name="library_download_original"),
    path("epreuves/", views.exam_list_view, name="exam_list"),
    path("epreuves/ajouter/", views.exam_create_view, name="exam_create"),
    path("epreuves/<int:pk>/modifier/", views.exam_edit_view, name="exam_edit"),
    path("epreuves/<int:pk>/statut/", views.exam_toggle_status_view, name="exam_toggle_status"),
    path("epreuves/<int:pk>/supprimer/", views.exam_delete_view, name="exam_delete"),
    path("completeness/", views.resource_completeness_view, name="completeness_overview"),

    # Résumés
    path("resumes/", views.summary_list_view, name="summary_list"),
    path("resumes/ajouter/", views.summary_create_view, name="summary_create"),
    path("resumes/<int:pk>/modifier/", views.summary_edit_view, name="summary_edit"),
    path("resumes/<int:pk>/statut/", views.summary_toggle_status_view, name="summary_toggle_status"),
    path("resumes/<int:pk>/supprimer/", views.summary_delete_view, name="summary_delete"),

    # Guides
    path("guides/", views.guide_list_view, name="guide_list"),
    path("guides/ajouter/", views.guide_create_view, name="guide_create"),
    path("guides/<int:pk>/modifier/", views.guide_edit_view, name="guide_edit"),
    path("guides/<int:pk>/statut/", views.guide_toggle_status_view, name="guide_toggle_status"),
    path("guides/<int:pk>/supprimer/", views.guide_delete_view, name="guide_delete"),

    # Conseils / Articles
    path("articles/", views.article_list_view, name="article_list"),
    path("articles/ajouter/", views.article_create_view, name="article_create"),
    path("articles/<int:pk>/modifier/", views.article_edit_view, name="article_edit"),
    path("articles/<int:pk>/statut/", views.article_toggle_status_view, name="article_toggle_status"),
    path("articles/<int:pk>/supprimer/", views.article_delete_view, name="article_delete"),

    # Matières / UE
    path("matieres/", views.subject_list_view, name="subject_list"),
    path("matieres/ajouter/", views.subject_create_view, name="subject_create"),
    path("matieres/<int:pk>/modifier/", views.subject_edit_view, name="subject_edit"),

    # Structure Académique
    path("structure/", views.structure_overview_view, name="structure_overview"),

    # Étudiants & Paiements
    path("etudiants/", views.student_list_view, name="student_list"),
    path("paiements/", views.payment_list_view, name="payment_list"),
    path("notifications/", views.notification_create_view, name="notification_create"),
]
