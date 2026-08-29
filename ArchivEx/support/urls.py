from django.urls import path
from . import views

app_name = "support"

urlpatterns = [
    # Student side
    path("", views.support_create_view, name="create"),
    path("mes-demandes/", views.support_list_view, name="list"),
    path("mes-demandes/<int:pk>/", views.support_detail_view, name="detail"),
]
