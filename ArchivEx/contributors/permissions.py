from functools import wraps
from django.core.exceptions import PermissionDenied


def check_school_permission(user, school):
    """Vérifie si l'utilisateur a la permission de gérer l'école donnée."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    profile = getattr(user, "contributor_profile", None)
    if not profile or not profile.is_active:
        return False

    return profile.can_manage_school(school)


def require_school_permission(school_id_param="school_id"):
    """Décorateur de vue qui applique la restriction stricte d'accès par école (Erreur HTTP 403)."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            school_id = kwargs.get(school_id_param) or request.GET.get(school_id_param) or request.POST.get(school_id_param)
            if not check_school_permission(request.user, school_id):
                raise PermissionDenied("Accès refusé : vous n'êtes pas autorisé à gérer le contenu de cette école.")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
