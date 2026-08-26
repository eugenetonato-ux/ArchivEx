from django.conf import settings
from django.db import models


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ("NEW_EXAM", "Nouvelle Épreuve"),
        ("NEW_SUMMARY", "Nouveau Résumé"),
        ("NEW_GUIDE", "Nouveau Guide"),
        ("NEW_ADVICE", "Nouveau Conseil"),
        ("PREMIUM", "Offre Premium"),
        ("PAYMENT", "Paiement & Accès"),
        ("SYSTEM", "Information Système"),
    ]

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default="SYSTEM")
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True, default="")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_notification_type_display()} pour {self.recipient.username}: {self.title}"
