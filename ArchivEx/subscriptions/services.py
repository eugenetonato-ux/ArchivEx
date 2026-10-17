from django.utils import timezone
from django.db.models import Q
from payments.models import SemesterAccess


def get_user_active_accesses(user):
    """Retourne le QuerySet de tous les SemesterAccess actifs de l'utilisateur."""
    if not user or not user.is_authenticated:
        return SemesterAccess.objects.none()
    legacy_query = Q(user=user) & (
        Q(activated_at__isnull=False) |
        Q(payments__status__in=["APPROVED", "reussi", "approved", "success"])
    )
    return SemesterAccess.objects.filter(legacy_query).distinct()


def user_has_any_active_pass(user):
    """Vérifie si l'utilisateur possède n'importe quel Pass actif sur la plateforme."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or getattr(user, "contributor_profile", None):
        return True

    if get_user_active_accesses(user).exists():
        return True

    from payments.models import Payment
    if Payment.objects.filter(user=user, status__in=["APPROVED", "reussi", "approved", "success"]).exists():
        return True

    from subscriptions.models import UserSubscription
    now = timezone.now()
    return UserSubscription.objects.filter(
        user=user,
        is_active=True,
        start_date__lte=now,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists()


def has_user_valid_pass(user, resource=None):
    """
    Vérifie si l'utilisateur possède un Pass Semestre actif pour la ressource demandée.
    Prend en charge tous types d'objets (Semester, Filiere, Subject, Exam, Summary, Guide) ou None.
    RÈGLE ARCHIVEX STRICTE :
    - Un Pass acheté pour un semestre d'une filière donnée (ex: S1 PGP) donne UNIQUEMENT
      accès aux ressources de ce semestre de cette filière.
    - Il n'accorde JAMAIS d'accès aux autres filières, même dans la même école.
    - Il n'accorde JAMAIS d'accès aux autres semestres (ex: S1 ne donne pas accès à S2).
    - Si le semestre est désactivé administrativement, l'accès est immédiatement refusé.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or user.is_staff or getattr(user, "contributor_profile", None):
        return True

    if resource is None:
        return user_has_any_active_pass(user)

    now = timezone.now()

    # Extraire le contexte académique de la ressource
    from academics.models import Semester, Filiere, Subject, School
    from payments.models import Payment, SemesterAccess
    from subscriptions.models import UserSubscription

    res_subject = getattr(resource, "subject", None)
    if isinstance(resource, Subject):
        res_subject = resource

    res_semester = getattr(resource, "semester", None)
    if isinstance(resource, Semester):
        res_semester = resource
    elif not res_semester and res_subject:
        res_semester = getattr(res_subject, "semester", None)

    res_filiere = getattr(resource, "filiere", None)
    if isinstance(resource, Filiere):
        res_filiere = resource
    elif not res_filiere and res_semester:
        res_filiere = getattr(res_semester, "filiere", None)

    res_school = getattr(resource, "school", None)
    if isinstance(resource, School):
        res_school = resource
    elif not res_school and res_filiere:
        res_school = getattr(res_filiere, "school", None)

    # 1. Si la ressource est liée à un semestre désactivé (ex: S2 fermé administrativement)
    if res_semester and not getattr(res_semester, "is_active", True):
        return False

    legacy_query = Q(user=user) & (
        Q(activated_at__isnull=False) |
        Q(payments__status__in=["APPROVED", "reussi", "approved", "success"])
    )

    # 2. Si la ressource est rattachée à un semestre spécifique (épreuves, corrigés, matières, résumés)
    if res_semester:
        # A. Vérification SemesterAccess pour CE semestre exact
        if SemesterAccess.objects.filter(legacy_query & Q(semester=res_semester)).exists():
            return True

        # B. Vérification paiement direct validé pour CE semestre exact
        if Payment.objects.filter(
            user=user, semester=res_semester,
            status__in=["APPROVED", "reussi", "approved", "success"]
        ).exists():
            return True

        # C. Vérification UserSubscription pour CE semestre exact
        if UserSubscription.objects.filter(
            user=user, semester=res_semester, is_active=True,
            start_date__lte=now,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists():
            return True

        # D. Basculement de bienveillance S2 -> S1 :
        # Si la ressource est pour le Semestre 1 et que l'utilisateur avait souscrit pour le Semestre 2 de la même filière,
        # l'accès au Semestre 1 lui est directement accordé.
        if getattr(res_semester, "number", 1) == 1 and res_filiere:
            s2_query = Q(semester__number=2, semester__filiere=res_filiere)
            if SemesterAccess.objects.filter(legacy_query & s2_query).exists():
                return True
            if Payment.objects.filter(
                user=user, semester__number=2, semester__filiere=res_filiere,
                status__in=["APPROVED", "reussi", "approved", "success"]
            ).exists():
                return True
            if UserSubscription.objects.filter(
                user=user, semester__number=2, semester__filiere=res_filiere, is_active=True,
                start_date__lte=now,
            ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists():
                return True

        # D. Vérification abonnement de portée supérieure explicite (Pass Filière annuel ou Pass École)
        if res_filiere and UserSubscription.objects.filter(
            user=user, filiere=res_filiere, is_active=True,
            start_date__lte=now,
        ).filter(Q(plan__scope__in=["program", "annual"]) | Q(semester__isnull=True, plan__isnull=True)).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists():
            return True

        if res_school and UserSubscription.objects.filter(
            user=user, school=res_school, is_active=True,
            start_date__lte=now,
        ).filter(Q(plan__scope="school") | Q(semester__isnull=True, filiere__isnull=True)).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists():
            return True

        # Si un semestre est spécifié et que l'utilisateur n'a pas de pass pour ce semestre : REFUS STRICT
        return False

    # 3. Ressource générale de filière sans semestre spécifié
    if res_filiere:
        if SemesterAccess.objects.filter(legacy_query & Q(filiere=res_filiere, semester__is_active=True)).exists():
            return True
        if UserSubscription.objects.filter(
            user=user, filiere=res_filiere, is_active=True,
            start_date__lte=now,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists():
            return True

    # 4. Ressource générale d'école (Pass École explicite uniquement)
    if res_school:
        if UserSubscription.objects.filter(
            user=user, school=res_school, is_active=True,
            plan__scope="school",
            start_date__lte=now,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now)).exists():
            return True

    return False


def can_user_access(user, resource):
    """
    Service centralisé de contrôle d'accès ArchivEx.

    RÈGLE ARCHIVEX :
    1. Toutes les épreuves (Exam) et ressources d'accès libre sont 100% GRATUITES.
       -> Accès accordé immédiatement à tous les étudiants sans nécessiter de Pass.
    2. Seuls les CORRIGÉS et les RÉSUMÉS de cours sont PAYANTS.
       -> Nécessitent un Pass actif (ou statut Staff).
    """
    if not resource:
        return False

    # Les épreuves d'examen (Exam) sont 100% gratuites en accès libre
    from exams.models import Exam
    if isinstance(resource, Exam):
        return True

    # 1. Vérification de gratuité générale (directe ou héritée de la matière)
    is_free_attr = getattr(resource, "is_free", False)
    if callable(is_free_attr):
        is_free = is_free_attr()
    else:
        is_free = bool(is_free_attr)

    if not is_free and getattr(resource, "access_type", None) == "FREE":
        is_free = True

    if not is_free:
        subj = getattr(resource, "subject", None)
        if subj and getattr(subj, "is_free", False):
            is_free = True

    if is_free:
        return True

    # 2. Pour les ressources payantes / premium, connexion obligatoire
    if not user or not user.is_authenticated:
        return False

    return has_user_valid_pass(user, resource)


def can_user_access_exam_pdf(user, exam):
    """Accès au PDF de l'épreuve principale.
    RÈGLE ARCHIVEX : Toutes les épreuves (sujets d'examen) sont 100% GRATUITES pour tous les étudiants.
    Aucun Pass ni paiement n'est exigé pour consulter le sujet d'une épreuve.
    """
    if not exam:
        return False
    return True


def can_user_access_correction(user, exam):
    """Accès à la correction PDF.
    RÈGLE ARCHIVEX : Tous les corrigés sont exclusivement Premium.
    Aucun corrigé n'est jamais gratuit. Nécessite obligatoirement un Pass actif (ou statut Staff).
    """
    if not exam:
        return False
    if not user or not user.is_authenticated:
        return False
    return has_user_valid_pass(user, exam)


def can_user_access_summary(user, resource):
    """Accès au résumé / fiche PDF.
    RÈGLE ARCHIVEX : Tous les résumés sont exclusivement Premium.
    Aucun résumé n'est jamais gratuit. Nécessite obligatoirement un Pass actif (ou statut Staff).
    """
    if not resource:
        return False
    if not user or not user.is_authenticated:
        return False
    return has_user_valid_pass(user, resource)


