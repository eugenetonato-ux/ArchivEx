from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    SCOPE_CHOICES = [
        ("semester", "Pass Semestre"),
        ("annual", "Pass Annuel"),
        ("school", "Pass École"),
        ("program", "Pass Filière"),
    ]

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="semester")
    price = models.PositiveIntegerField(default=2000, help_text="Prix en FCFA")
    duration_days = models.PositiveIntegerField(default=180, help_text="Durée de validité en jours")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price", "name"]

    def __str__(self):
        return f"{self.name} ({self.price} FCFA)"


class UserSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="user_subscriptions")
    school = models.ForeignKey("academics.School", on_delete=models.PROTECT, null=True, blank=True)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT, null=True, blank=True)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT, null=True, blank=True)
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT, null=True, blank=True)

    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    payment = models.ForeignKey("payments.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="granted_subscriptions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_currently_valid(self):
        if not self.is_active:
            return False
        if self.end_date and timezone.now() > self.end_date:
            return False
        return True

    def __str__(self):
        scope_str = self.semester or self.filiere or self.school or "Global"
        return f"Abonnement {self.user.username} - {scope_str}"
