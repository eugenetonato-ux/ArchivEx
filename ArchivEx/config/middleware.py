from django.shortcuts import render
from django.conf import settings


class MaintenanceModeMiddleware:
    """
    Middleware de mode maintenance ArchivEx.
    Quand MAINTENANCE_MODE=True dans les settings, tout visiteur
    non-staff voit la belle page maintenance (HTTP 503).
    Les bots (Googlebot) sont laissés passer pour ne pas perdre l'indexation.
    """

    ALLOWED_PATHS = [
        "/django-admin/",
        "/administration/",
    ]

    # User-agents autorisés à passer en maintenance (bots de qualité)
    ALLOWED_BOTS = [
        "googlebot",
        "bingbot",
        "facebookexternalhit",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "MAINTENANCE_MODE", False):
            return self.get_response(request)

        # Laisser passer les administrateurs connectés
        if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
            return self.get_response(request)

        # Laisser passer les URLs d'administration
        for path in self.ALLOWED_PATHS:
            if request.path.startswith(path):
                return self.get_response(request)

        # Laisser passer les bots de recherche (pour ne pas perdre l'indexation)
        user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
        for bot in self.ALLOWED_BOTS:
            if bot in user_agent:
                return self.get_response(request)

        # Afficher la page de maintenance (503 Service Unavailable)
        response = render(request, "maintenance.html", status=503)
        response["Retry-After"] = "86400"
        return response
