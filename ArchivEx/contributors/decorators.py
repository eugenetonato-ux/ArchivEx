from functools import wraps
from urllib.parse import urlencode
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from academics.models import School, Filiere, Semester


def is_user_contributor(user):
    """Vérifie si l'utilisateur est authentifié et autorisé à accéder au portail d'administration."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, "contributor_profile", None)
    if profile:
        return bool(profile.is_active)
    return False


def contributor_required(view_func):
    """
    Décorateur de vue exigeant une authentification staff/contributeur
    pour l'accès au portail d'administration (/administration/).
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("contributors:admin_login")
            next_url = request.path
            return redirect(f"{login_url}?{urlencode({'next': next_url})}")

        if not is_user_contributor(request.user):
            raise PermissionDenied("Accès refusé : espace réservé aux membres du personnel et administrateurs.")

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_active_academic_context(request):
    """
    Récupère le contexte académique actif (Université + Filière + Semestre) de la session du contributeur.
    Si non initialisé, sélectionne automatiquement la première université, filière et semestre disponibles.
    """
    user = getattr(request, "user", None)

    active_school = None
    active_filiere = None
    active_semester = None

    school_id = request.session.get("admin_active_school_id")
    filiere_id = request.session.get("admin_active_filiere_id")
    semester_id = request.session.get("admin_active_semester_id")

    # 1. Validation de l'école active
    if school_id:
        active_school = School.objects.filter(id=school_id, is_active=True).first()

    if not active_school and user and user.is_authenticated:
        profile = getattr(user, "contributor_profile", None)
        if profile and profile.assigned_schools.exists():
            active_school = profile.assigned_schools.filter(is_active=True).first()
        else:
            active_school = School.objects.filter(is_active=True).first()

        if active_school:
            request.session["admin_active_school_id"] = active_school.id
    elif not active_school:
        active_school = School.objects.filter(is_active=True).first()
        if active_school:
            request.session["admin_active_school_id"] = active_school.id

    # 2. Validation de la filière active
    if filiere_id:
        active_filiere = Filiere.objects.filter(id=filiere_id).first()
        if active_filiere and active_school and active_filiere.school_id != active_school.id:
            active_filiere = None

    if not active_filiere and active_school:
        active_filiere = Filiere.objects.filter(school=active_school).first()
        if active_filiere:
            request.session["admin_active_filiere_id"] = active_filiere.id

    # 3. Validation du semestre actif
    if semester_id:
        active_semester = Semester.objects.filter(id=semester_id).first()
        if active_semester and active_filiere and active_semester.filiere_id != active_filiere.id:
            active_semester = None

    if not active_semester and active_filiere:
        active_semester = Semester.objects.filter(filiere=active_filiere).first()
        if active_semester:
            request.session["admin_active_semester_id"] = active_semester.id

    return active_school, active_filiere, active_semester
