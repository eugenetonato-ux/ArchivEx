from .models import Notification


def notifications_context(request):
    if request.user.is_authenticated:
        # Pour les membres du staff / contributeurs / superutilisateurs :
        # Exclure les notifications de contenu académique (épreuves, corrigés, résumés, guides)
        # qui s'adressent exclusivement aux étudiants afin d'éviter toute confusion dans l'espace staff.
        user = request.user
        if user.is_staff or getattr(user, "is_superuser", False) or hasattr(user, "contributor_profile"):
            qs = Notification.objects.filter(recipient=user).exclude(
                notification_type__in=["NEW_EXAM", "NEW_CORRECTION", "NEW_SUMMARY", "NEW_GUIDE", "NEW_ADVICE"]
            )
        else:
            qs = Notification.objects.filter(recipient=user)

        unread_count = qs.filter(is_read=False).count()
        recent_notifications = qs.order_by("-created_at")[:5]
        return {
            "unread_notifications_count": unread_count,
            "recent_notifications": recent_notifications,
        }
    return {
        "unread_notifications_count": 0,
        "recent_notifications": [],
    }
