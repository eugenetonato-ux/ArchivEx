from academics.models import School
from .context import get_current_school
from django.core.cache import cache


def academic_school_context(request):
    """
    Context processor global injectant l'ecole active (current_school)
    et la liste des ecoles actives (available_schools) dans tous les templates du site.
    La liste des ecoles est mise en cache 5 minutes (donnee quasi-statique).
    """
    current_school = get_current_school(request)

    # Cache la liste des ecoles — change tres rarement, evite 1 requete Supabase par page
    available_schools = cache.get("available_schools_list")
    if available_schools is None:
        available_schools = list(School.objects.filter(is_active=True).order_by("name"))
        cache.set("available_schools_list", available_schools, 300)

    is_student_locked_to_school = False
    if request.user.is_authenticated and hasattr(request.user, "profile") and request.user.profile.school:
        if not (request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None)):
            is_student_locked_to_school = True

    return {
        "current_school": current_school,
        "available_schools": available_schools,
        "is_student_locked_to_school": is_student_locked_to_school,
    }
