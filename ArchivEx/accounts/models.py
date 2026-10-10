from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """Utilisateur ArchivEx (étudiant ou administrateur)."""
    must_change_password = models.BooleanField(
        default=False,
        verbose_name="Doit modifier son mot de passe",
        help_text="Forcer l'utilisateur à modifier son mot de passe dès sa prochaine connexion.",
    )
    active_session_key = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        verbose_name="Clé de session active",
        help_text="Stocke la clé de session actuellement valide pour empêcher les connexions simultanées.",
    )


from django.core.files.storage import FileSystemStorage

fs_storage = FileSystemStorage()


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    school = models.ForeignKey("academics.School", on_delete=models.PROTECT)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT)
    avatar = models.ImageField(upload_to="avatars/", storage=fs_storage, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.filiere}"


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorites")
    exam = models.ForeignKey("exams.Exam", on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "exam")

    def __str__(self):
        return f"{self.user.username} {self.exam.title}"


class SiteLog(models.Model):
    ACTION_CHOICES = (
        ("CONNECTION", "Connexion / Déconnexion"),
        ("MODIFICATION", "Modification de contenu"),
        ("CLICK", "Clic Bouton / Lien public"),
        ("PAGE_VIEW", "Consultation de page"),
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="site_logs")
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES)
    description = models.TextField()
    path = models.CharField(max_length=255, blank=True, null=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        user_str = self.user.username if self.user else "Anonyme"
        return f"[{self.get_action_type_display()}] {user_str} - {self.description[:50]}"


class UserDevice(models.Model):
    """
    Appareil autorisé pour le compte étudiant.
    Limite stricte à 2 appareils maximum simultanés pour neutraliser le partage de compte.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=64, db_index=True)
    device_name = models.CharField(max_length=100, default="Appareil")
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    last_login = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "device_id")
        ordering = ["-last_login"]

    def __str__(self):
        return f"{self.user.username} — {self.device_name}"


class DeviceRevocationLog(models.Model):
    """
    Journalise chaque révocation ou remplacement d'appareil pour imposer
    la règle de sécurité anti-partage : maximum 2 révocations par 24h.
    Au-delà, tout nouveau remplacement est suspendu pendant 24h.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_revocations")
    revoked_device_name = models.CharField(max_length=100, blank=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} — Révocation {self.revoked_device_name} ({self.created_at})"