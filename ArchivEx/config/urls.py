from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("administration/", include("contributors.urls")),
    path("", include("academics.urls")),
    path("", include("accounts.urls")),
    path("epreuves/", include("exams.urls")),
    path("pass/", include("payments.urls")),
    path("ressources/", include("content.urls")),
    path("notifications/", include("notifications.urls")),
]

handler403 = "academics.views.custom_403_view"
handler404 = "academics.views.custom_404_view"
handler500 = "academics.views.custom_500_view"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

