from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("<int:pk>/lire/", views.mark_notification_read, name="mark_read"),
    path("tout-lire/", views.mark_all_read, name="mark_all_read"),
]
