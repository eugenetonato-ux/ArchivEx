from django.urls import reverse
from accounts.models import StudentProfile
from .models import Notification


def notify_target_students(school=None, level=None, filiere=None, notification_type="SYSTEM", title="", message="", link=""):
    """
    Envoie des notifications ciblées aux étudiants dont le profil académique
    correspond aux critères spécifiés (École, Niveau, Filière).
    """
    profiles = StudentProfile.objects.all().select_related("user")

    if school:
        profiles = profiles.filter(school=school)
    if level:
        profiles = profiles.filter(level=level)
    if filiere:
        profiles = profiles.filter(filiere=filiere)

    target_users = set(p.user for p in profiles if p.user.is_active)

    if not target_users:
        return 0

    notifications_to_create = [
        Notification(
            recipient=user,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link
        )
        for user in target_users
    ]

    Notification.objects.bulk_create(notifications_to_create)
    return len(notifications_to_create)


def generate_publication_notification(instance, nature="epreuve"):
    """
    Génère automatiquement une notification spontanée et rédigée selon la nature
    de la publication (épreuve, corrigé, résumé, guide) et le nom de la matière.
    
    natures supportées:
    - 'epreuve' / 'NEW_EXAM'
    - 'corrige' / 'NEW_CORRECTION'
    - 'resume' / 'NEW_SUMMARY'
    - 'guide' / 'NEW_GUIDE'
    """
    subject_name = ""
    school = None
    filiere = None
    level = None
    link = ""

    # Extraire les métadonnées académiques selon la classe du modèle
    model_name = instance.__class__.__name__

    if model_name == "Exam":
        subject_name = instance.subject.name if instance.subject else "Matière"
        filiere = instance.filiere
        school = filiere.school if filiere else None
        level = instance.level
        try:
            link = reverse("exams:detail", kwargs={"pk": instance.pk})
        except Exception:
            link = f"/exams/{instance.pk}/"

    elif model_name == "Summary":
        subject_name = instance.subject.name if instance.subject else "Matière"
        filiere = instance.subject.semester.filiere if (instance.subject and instance.subject.semester) else None
        school = filiere.school if filiere else None
        level = filiere.level if filiere else None
        try:
            link = reverse("content:summary_detail", kwargs={"pk": instance.pk})
        except Exception:
            link = f"/content/resumes/{instance.pk}/"

    elif model_name == "Guide":
        subject_name = instance.subject.name if instance.subject else "Matière"
        filiere = instance.subject.semester.filiere if (instance.subject and instance.subject.semester) else None
        school = filiere.school if filiere else None
        level = filiere.level if filiere else None
        try:
            link = reverse("content:guide_detail", kwargs={"pk": instance.pk})
        except Exception:
            link = f"/content/guides/{instance.pk}/"

    # Normalisation du type et formulation spontanée des textes
    nature_lower = str(nature).lower()

    if nature_lower in ["corrige", "correction", "new_correction"]:
        notification_type = "NEW_CORRECTION"
        title = f"Nouveau corrigé : {subject_name}"
        message = f"Un corrigé de {subject_name} est disponible. Cliquez pour consulter les réponses et explications."
    elif nature_lower in ["resume", "summary", "new_summary"]:
        notification_type = "NEW_SUMMARY"
        title = f"Nouveau résumé : {subject_name}"
        message = f"Un résumé du cours {subject_name} est disponible, cliquez pour consulter."
    elif nature_lower in ["guide", "new_guide"]:
        notification_type = "NEW_GUIDE"
        title = f"Nouveau guide : {subject_name}"
        message = f"Un guide méthodologique pour {subject_name} est disponible, cliquez pour consulter."
    else:  # epreuve / NEW_EXAM
        notification_type = "NEW_EXAM"
        title = f"Nouvelle épreuve : {subject_name}"
        year_str = f" ({instance.year})" if getattr(instance, "year", None) else ""
        message = f"L'épreuve de {subject_name}{year_str} est disponible sur ArchivEx. Cliquez pour consulter."

    # Déduplication : Vérifier si une notification pour cette ressource et ce type existe déjà
    if link and Notification.objects.filter(link=link, notification_type=notification_type).exists():
        return 0

    return notify_target_students(
        school=school,
        level=level,
        filiere=filiere,
        notification_type=notification_type,
        title=title,
        message=message,
        link=link,
    )

