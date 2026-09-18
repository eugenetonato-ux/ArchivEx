import re
from .utils import log_user_action

class SiteLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Exclude patterns for static resources, media, and the logging API itself
        self.exclude_patterns = [
            r'^/static/',
            r'^/media/',
            r'^/accounts/api/log-click/',
            r'^/favicon\.ico',
            r'^/icons/',
            r'^/manifest\.json',
            r'^/service-worker\.js',
            r'^/administration/site-logs/',
            r'^/contributors/site-logs/',
        ]

    def __call__(self, request):
        path = request.path
        
        # Check if the path should be excluded from logs
        should_exclude = False
        for pattern in self.exclude_patterns:
            if re.match(pattern, path):
                should_exclude = True
                break
                
        if should_exclude:
            return self.get_response(request)

        # Before view execution: Let's log the page view for GET requests on main user paths
        if request.method == "GET":
            # Clean page view messages for readable logs
            if path == "/":
                description = "Consultation de la page d'accueil publique"
            elif path.startswith("/accounts/dashboard/"):
                description = "Consultation du tableau de bord étudiant"
            elif path.startswith("/contributors/"):
                description = f"Consultation de l'interface de contribution : {path}"
            elif path.startswith("/exams/"):
                description = f"Consultation d'une épreuve ou ressource académique : {path}"
            else:
                description = f"Consultation de la page : {path}"
                
            log_user_action(request, "PAGE_VIEW", description)

        # Execute response
        response = self.get_response(request)

        # After view execution: Log modifications for POST requests
        if request.method in ["POST", "PUT", "DELETE"] and response.status_code in [200, 302]:
            # Skip standard authentication pages to avoid duplicate login logs
            auth_paths = ["/accounts/connexion/", "/accounts/inscription/", "/accounts/deconnexion/", "/accounts/api/log-click/"]
            if not any(ap in path for ap in auth_paths):
                desc = f"Action de modification ou création validée sur l'URL : {path}"
                # Let's inspect the request POST data for extra descriptive details
                if "title" in request.POST:
                    desc += f" (Titre : '{request.POST.get('title')}')"
                elif "ue_name" in request.POST:
                    desc += f" (UE : '{request.POST.get('ue_name')}')"
                
                log_user_action(request, "MODIFICATION", desc)

        return response


class MustChangePasswordMiddleware:
    """
    Middleware de sécurité :
    Si un utilisateur a le flag must_change_password = True,
    il est immédiatement redirigé vers la page de modification obligatoire de mot de passe,
    l'empêchant d'accéder au reste du site tant qu'il n'a pas défini son mot de passe personnel.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "must_change_password", False):
            from django.urls import reverse
            from django.shortcuts import redirect

            path = request.path
            allowed_paths = [
                reverse("accounts:force_password_change"),
                reverse("accounts:logout"),
            ]

            is_exempt = (
                path in allowed_paths
                or path.startswith("/static/")
                or path.startswith("/media/")
                or path.startswith("/favicon.ico")
            )

            if not is_exempt:
                return redirect("accounts:force_password_change")

        return self.get_response(request)
