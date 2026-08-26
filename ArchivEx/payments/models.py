from django.conf import settings
from django.db import models


class SemesterAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accesses")
    school = models.ForeignKey("academics.School", on_delete=models.PROTECT)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("user", "semester")

    def __str__(self):
        return f"{self.user} - {self.semester}"


class Payment(models.Model):
    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("reussi", "Réussi"),
        ("echoue", "Échoué"),
        ("annule", "Annulé"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    semester_access = models.ForeignKey(SemesterAccess, on_delete=models.PROTECT, related_name="payments")
    amount = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUT_CHOICES, default="en_attente")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.amount} FCFA - {self.status}"