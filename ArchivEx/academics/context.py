from django.db.models import Q
from academics.models import School


def get_current_school(request):
    """
    Détermine l'école (université / institut) active pour la requête :
    1. Paramètre GET explicite : ?school=<id|slug|code>
       - Valide l'école et la mémorise en session.
       - Si l'utilisateur est staff/contributeur, synchronise aussi le contexte admin.
    2. Étudiant authentifié :
       - Strictement et obligatoirement verrouillé sur request.user.profile.school.
       - Un étudiant ne peut pas voir les documents d'une autre université.
    3. Contributeur / Administrateur authentifié :
       - Récupère l'école active depuis request.session['admin_active_school_id'].
       - Ou la première école assignée dans son profil contributeur.
    4. Session visiteur :
       - request.session['current_school_id'].
    5. Fallback utilisateur (au cas où non couvert par les règles ci-dessus) :
       - request.user.profile.school si existant.
    6. Défaut général :
       - Première école active de la base de données.
    """
    # 1. Paramètre GET explicite (?school=...)
    school_param = request.GET.get("school")
    if school_param:
        school_param = str(school_param).strip()
        matched_school = School.objects.filter(
            Q(id=school_param if school_param.isdigit() else -1) |
            Q(slug=school_param) |
            Q(code__iexact=school_param),
            is_active=True
        ).first()

        if matched_school:
            # Pour un étudiant standard, son école est fixée par son inscription
            is_pure_student = (
                request.user.is_authenticated and
                hasattr(request.user, "profile") and
                not (request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None))
            )
            if not is_pure_student:
                request.session["current_school_id"] = matched_school.id
                if request.user.is_authenticated and (request.user.is_staff or getattr(request.user, "contributor_profile", None)):
                    request.session["admin_active_school_id"] = matched_school.id
                return matched_school

    # 2. Étudiant connecté ordinaire (verrouillage strict sur son école d'inscription)
    if request.user.is_authenticated and hasattr(request.user, "profile") and request.user.profile.school:
        if not (request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None)):
            return request.user.profile.school

    # 3. Administrateur / Staff / Contributeur
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None)):
        admin_school_id = request.session.get("admin_active_school_id") or request.session.get("current_school_id")
        if admin_school_id:
            s = School.objects.filter(id=admin_school_id, is_active=True).first()
            if s:
                return s
        c_profile = getattr(request.user, "contributor_profile", None)
        if c_profile and c_profile.assigned_schools.filter(is_active=True).exists():
            return c_profile.assigned_schools.filter(is_active=True).first()

    # 4. Session visiteur public
    session_school_id = request.session.get("current_school_id")
    if session_school_id:
        s = School.objects.filter(id=session_school_id, is_active=True).first()
        if s:
            return s

    # 5. Profil étudiant si disponible
    if request.user.is_authenticated and hasattr(request.user, "profile") and request.user.profile.school:
        return request.user.profile.school

    # 6. Première école active
    first_school = School.objects.filter(is_active=True).first()
    if first_school and "current_school_id" not in request.session:
        request.session["current_school_id"] = first_school.id
    return first_school
