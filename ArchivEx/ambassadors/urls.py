from django.urls import path
from . import views
from . import admin_views

app_name = "ambassadors"

urlpatterns = [
    path("administration/", admin_views.ambassador_admin_list_view, name="admin_list"),
    path("api/verifier-code/", views.verify_referral_code_api, name="verify_code_api"),
    path("<str:token>/", views.ambassador_dashboard_view, name="dashboard"),
]

