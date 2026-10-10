from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from payments.views import fedapay_webhook_view, payment_return_view
from academics import views as academic_views
from django.contrib.sitemaps.views import sitemap
from config.sitemaps import (
    StaticViewSitemap,
    SchoolSitemap,
    FiliereSitemap,
    SemesterSitemap,
    SubjectSitemap,
    ExamSitemap,
    SummarySitemap,
    GuideSitemap,
    ArticleSitemap,
)

sitemaps = {
    "static": StaticViewSitemap,
    "schools": SchoolSitemap,
    "filieres": FiliereSitemap,
    "semesters": SemesterSitemap,
    "subjects": SubjectSitemap,
    "exams": ExamSitemap,
    "summaries": SummarySitemap,
    "guides": GuideSitemap,
    "articles": ArticleSitemap,
}


def clean_sitemap_view(request, **kwargs):
    """Génère le sitemap sans l'en-tête X-Robots-Tag noindex de Django."""
    response = sitemap(request, **kwargs)
    try:
        del response["X-Robots-Tag"]
    except KeyError:
        pass
    return response


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("administration/", include("contributors.urls")),
    path("", include("academics.urls")),
    path("", include("accounts.urls")),
    path("epreuves/", include("exams.urls")),
    path("pass/", include("payments.urls")),
    path("payment/success/", payment_return_view, name="payment_success_return"),
    path("webhook/fedapay/", fedapay_webhook_view, name="root_fedapay_webhook"),

    path("ressources/", include("content.urls")),
    path("notifications/", include("notifications.urls")),
    path("support/", include("support.urls")),
    path("robots.txt", academic_views.robots_txt_view, name="robots_txt"),
    path("sitemap.xml", clean_sitemap_view, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),
    path("google4fc7f01109e31c86.html", lambda request: HttpResponse("google-site-verification: google4fc7f01109e31c86.html", content_type="text/html")),
    path("service-worker.js", academic_views.service_worker_view, name="service_worker"),
    path("manifest.json", academic_views.manifest_view, name="manifest_json"),
    path("icons/icon-192.png", academic_views.icon_192_view, name="pwa_icon_192"),
    path("icons/icon-512.png", academic_views.icon_512_view, name="pwa_icon_512"),
    path("favicon.ico", academic_views.favicon_view, name="favicon"),
]

handler403 = "academics.views.custom_403_view"
handler404 = "academics.views.custom_404_view"
handler500 = "academics.views.custom_500_view"

from django.views.static import serve
from django.urls import re_path
from django.http import HttpResponseForbidden

def safe_media_serve(request, path, document_root=None, show_indexes=False):
    """
    Sert les fichiers médias publics (couvertures d'UE, logos, avatars).
    Bloque l'accès direct aux épreuves brutes non filigranées (exams/, corrections/, cache/).
    """
    normalized_path = path.replace("\\", "/").strip("/")
    if any(normalized_path.startswith(prefix) for prefix in ["exams/", "corrections/", "cache/"]):
        return HttpResponseForbidden("Accès restreint. Document protégé par ArchivEx.")
    return serve(request, path, document_root=document_root, show_indexes=show_indexes)

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", safe_media_serve, {"document_root": settings.MEDIA_ROOT}),
]

