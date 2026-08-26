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
