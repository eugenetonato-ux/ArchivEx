from academics.models import School
from .context import get_current_school


def academic_school_context(request):
    """
    Context processor global injectant l'école active (current_school)
    et la liste des écoles actives (available_schools) dans tous les templates du site.
    """
    current_school = get_current_school(request)
    available_schools = list(School.objects.filter(is_active=True).order_by("name"))

    is_student_locked_to_school = False
    if request.user.is_authenticated and hasattr(request.user, "profile") and request.user.profile.school:
        if not (request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None)):
            is_student_locked_to_school = True

    return {
        "current_school": current_school,
        "available_schools": available_schools,
        "is_student_locked_to_school": is_student_locked_to_school,
    }
