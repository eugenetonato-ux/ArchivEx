from django.conf import settings
from django.db import models


class SupportRequest(models.Model):
    """Demande de support soumise par un étudiant authentifié."""

    STATUS_CHOICES = [
        ("non_lu", "Non lu"),
        ("en_cours", "En cours"),
        ("repondu", "Répondu"),
        ("cloture", "Clôturé"),
    ]

    CATEGORY_CHOICES = [
        ("question", "Question"),
        ("probleme_epreuve", "Problème avec une épreuve"),
        ("probleme_compte", "Problème de compte"),
        ("paiement", "Paiement"),
        ("suggestion", "Suggestion"),
        ("signaler_erreur", "Signaler une erreur"),
        ("autre", "Autre"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_requests",
        verbose_name="Étudiant",
    )
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default="question",
        verbose_name="Catégorie / Motif",
    )
    message = models.TextField(verbose_name="Message")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="non_lu",
        verbose_name="Statut",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de soumission")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Demande de support"
        verbose_name_plural = "Demandes de support"

    def __str__(self):
        return f"[{self.get_status_display()}] {self.get_category_display()} — {self.user.get_full_name() or self.user.username}"

    @property
    def has_reply(self):
        return self.replies.exists()


class SupportReply(models.Model):
    """Réponse d'un administrateur à une demande de support étudiant."""

    request = models.ForeignKey(
        SupportRequest,
        on_delete=models.CASCADE,
        related_name="replies",
        verbose_name="Demande",
    )
    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="support_replies",
        verbose_name="Administrateur",
    )
    message = models.TextField(verbose_name="Réponse")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de réponse")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Réponse support"
        verbose_name_plural = "Réponses support"

    def __str__(self):
        return f"Réponse de {self.admin_user} à #{self.request.pk}"
