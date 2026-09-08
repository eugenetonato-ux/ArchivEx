from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.login_view, name="login"),
    path("inscription/", views.register_view, name="register"),
    path("deconnexion/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("favoris/", views.favorites_list_view, name="favoris"),
    path("profil/", views.profile_view, name="profile"),
    path("api/levels/", views.api_levels_view, name="api_levels"),
    path("api/filieres/", views.api_filieres_view, name="api_filieres"),
    path("api/log-click/", views.api_log_click_view, name="api_log_click"),
    path("accounts/api/log-click/", views.api_log_click_view, name="accounts_api_log_click"),
]

