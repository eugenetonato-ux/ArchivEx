from django.utils import timezone
from django.db.models import Q
from payments.models import SemesterAccess


def has_user_valid_pass(user, resource):
    """
    Vérifie si l'utilisateur possède un Pass Semestre / Filière / École actif.
    Seuls les superutilisateurs/staff et les étudiants avec un Pass valide retournent True.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or user.is_staff or getattr(user, "contributor_profile", None):
        return True

    now = timezone.now()

    # Extraire le contexte académique de la ressource
    res_subject = getattr(resource, "subject", None)
    res_semester = getattr(resource, "semester", None)
    if not res_semester and res_subject:
        res_semester = getattr(res_subject, "semester", None)

    res_filiere = getattr(resource, "filiere", None)
    if not res_filiere and res_semester:
        res_filiere = getattr(res_semester, "filiere", None)

    res_school = getattr(resource, "school", None)
    if not res_school and res_filiere:
        res_school = getattr(res_filiere, "school", None)

    # 1. Vérification SemesterAccess (Legacy V1)
    legacy_query = Q(user=user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
    if res_semester:
        if SemesterAccess.objects.filter(legacy_query & Q(semester=res_semester)).exists():
            return True

    if res_filiere:
        if SemesterAccess.objects.filter(legacy_query & Q(filiere=res_filiere)).exists():
            return True

    # 2. Vérification UserSubscription (V2)
    from subscriptions.models import UserSubscription

    active_subs = UserSubscription.objects.filter(
        user=user,
        is_active=True,
        start_date__lte=now,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now))

    for sub in active_subs:
        if not sub.school and not sub.filiere and not sub.semester:
            return True
        if sub.semester and res_semester and sub.semester_id == res_semester.id:
            return True
        if sub.filiere and res_filiere and sub.filiere_id == res_filiere.id:
            return True
        if sub.school and res_school and sub.school_id == res_school.id:
            return True

    return False


def can_user_access(user, resource):
    """
    Service centralisé de contrôle d'accès ArchivEx V2.

    Règles évaluées :
    1. Si la ressource est gratuite (is_free=True ou access_type='FREE') -> Accès accordé.
    2. Autrement -> nécessite un Pass valide ou statut Staff.
    """
    if not resource:
        return False

    # 1. Ressource gratuite
    is_free_attr = getattr(resource, "is_free", False)
    if callable(is_free_attr):
        is_free = is_free_attr()
    else:
        is_free = bool(is_free_attr)

    if not is_free and getattr(resource, "access_type", None) == "FREE":
        is_free = True

    if is_free:
        return True

    return has_user_valid_pass(user, resource)


def can_user_access_exam_pdf(user, exam):
    """Accès au PDF de l'épreuve principale : gratuit si exam.is_free, sinon Pass requis."""
    return can_user_access(user, exam)


def can_user_access_correction(user, exam):
    """
    Accès à la correction PDF : TOUJOURS PREMIUM.
    Même si l'épreuve parente est gratuite, la correction requiert un Pass valide.
    """
    if not exam:
        return False
    return has_user_valid_pass(user, exam)


def can_user_access_summary(user, resource):
    """
    Accès au résumé / fiche PDF : TOUJOURS PREMIUM.
    Même si l'épreuve parente est gratuite, le résumé requiert un Pass valide.
    """
    if not resource:
        return False
    return has_user_valid_pass(user, resource)

