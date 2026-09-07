from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from payments.views import sebpay_webhook_view, payment_return_view
from academics import views as academic_views

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("administration/", include("contributors.urls")),
    path("", include("academics.urls")),
    path("", include("accounts.urls")),
    path("epreuves/", include("exams.urls")),
    path("pass/", include("payments.urls")),
    path("payment/success/", payment_return_view, name="payment_success_return"),
    path("webhook/sebpay/", sebpay_webhook_view, name="root_sebpay_webhook"),
    path("ressources/", include("content.urls")),
    path("notifications/", include("notifications.urls")),
    path("support/", include("support.urls")),
    path("service-worker.js", academic_views.service_worker_view, name="service_worker"),
    path("manifest.json", academic_views.manifest_view, name="manifest_json"),
    path("icons/icon-192.png", academic_views.icon_192_view, name="pwa_icon_192"),
    path("icons/icon-512.png", academic_views.icon_512_view, name="pwa_icon_512"),
]

handler403 = "academics.views.custom_403_view"
handler404 = "academics.views.custom_404_view"
handler500 = "academics.views.custom_500_view"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

