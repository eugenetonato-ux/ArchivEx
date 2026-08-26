from academics.models import School, Filiere
from .decorators import get_active_academic_context


def admin_academic_context(request):
    """
    Context processor injectant le contexte académique actif (Université + Filière)
    ainsi que les listes d'écoles et filières disponibles dans tous les templates d'administration.
    """
    if not request.path.startswith("/administration/"):
        return {}

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    active_school, active_filiere = get_active_academic_context(request)

    # Déterminer les écoles accessibles pour cet utilisateur
    if user.is_superuser:
        available_schools = School.objects.filter(is_active=True)
    else:
        profile = getattr(user, "contributor_profile", None)
        if profile and profile.assigned_schools.exists():
            available_schools = profile.assigned_schools.filter(is_active=True)
        else:
            available_schools = School.objects.filter(is_active=True)

    # Récupérer les filières associées à l'école active
    if active_school:
        available_filieres = Filiere.objects.filter(school=active_school)
    else:
        available_filieres = Filiere.objects.none()

    return {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "available_schools": available_schools,
        "available_filieres": available_filieres,
    }
