from django.utils import timezone
from django.db.models import Q
from payments.models import SemesterAccess


def can_user_access(user, resource):
    """
    Service centralisé de contrôle d'accès ArchivEx V2.

    Règles évaluées :
    1. Si la ressource est gratuite (is_free=True ou access_type='FREE') -> Accès accordé.
    2. Si l'utilisateur n'est pas authentifié -> Accès refusé.
    3. Si l'utilisateur est Superadministrateur ou Staff -> Accès accordé.
    4. Vérification des accès SemesterAccess actifs (Compatibilité V1).
    5. Vérification des abonnements UserSubscription actifs (SaaS V2).
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


    # 2. Utilisateur non authentifié
    if not user or not user.is_authenticated:
        return False

    # 3. Superutilisateur / Staff
    if user.is_superuser or user.is_staff:
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


    # 4. Vérification SemesterAccess (Legacy V1)
    legacy_query = Q(user=user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
    if res_semester:
        legacy_has_access = SemesterAccess.objects.filter(legacy_query & Q(semester=res_semester)).exists()
        if legacy_has_access:
            return True

    if res_filiere:
        legacy_filiere_access = SemesterAccess.objects.filter(legacy_query & Q(filiere=res_filiere)).exists()
        if legacy_filiere_access:
            return True

    # 5. Vérification UserSubscription (V2)
    from subscriptions.models import UserSubscription

    active_subs = UserSubscription.objects.filter(
        user=user,
        is_active=True,
        start_date__lte=now,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now))

    for sub in active_subs:
        # Abonnement global (sans restriction)
        if not sub.school and not sub.filiere and not sub.semester:
            return True

        # Abonnement restreint par semestre
        if sub.semester and res_semester and sub.semester_id == res_semester.id:
            return True

        # Abonnement restreint par filière
        if sub.filiere and res_filiere and sub.filiere_id == res_filiere.id:
            return True

        # Abonnement restreint par école
        if sub.school and res_school and sub.school_id == res_school.id:
            return True

    return False
