from django.conf import settings
from django.db import models


class ContributorProfile(models.Model):
    ROLE_CHOICES = [
        ("SUPER_ADMIN", "Super Administrateur"),
        ("CONTENT_MANAGER", "Gestionnaire de Contenu Global"),
        ("SCHOOL_CONTENT_MANAGER", "Gestionnaire de Contenu d'École"),
        ("EDITOR", "Rédacteur / Relecteur"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contributor_profile")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default="EDITOR")
    assigned_schools = models.ManyToManyField("academics.School", blank=True, related_name="contributors")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def can_manage_school(self, school):
        if not self.is_active:
            return False
        if self.user.is_superuser or self.role in ["SUPER_ADMIN", "CONTENT_MANAGER"]:
            return True
        if not school:
            return False
        school_id = school.id if hasattr(school, "id") else school
        return self.assigned_schools.filter(id=school_id).exists()

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
