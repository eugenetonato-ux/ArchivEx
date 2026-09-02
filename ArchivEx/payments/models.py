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
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_CANCELLED = "CANCELLED"

    STATUT_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Payé / Réussi"),
        (STATUS_REJECTED, "Rejeté / Échoué"),
        (STATUS_EXPIRED, "Expiré"),
        (STATUS_CANCELLED, "Annulé"),
        # Legacy status values for backward compatibility
        ("en_attente", "En attente (ancien)"),
        ("reussi", "Réussi (ancien)"),
        ("echoue", "Échoué (ancien)"),
        ("annule", "Annulé (ancien)"),
    ]

    OPERATOR_CHOICES = [
        ("mtn", "MTN Money"),
        ("moov", "Moov Money"),
        ("celtiis", "Celtiis Money"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT, related_name="payments", null=True, blank=True)
    semester_access = models.ForeignKey(SemesterAccess, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=10, default="XOF")
    operator = models.CharField(max_length=20, choices=OPERATOR_CHOICES, default="mtn")
    phone_number = models.CharField(max_length=20, blank=True)
    
    external_reference = models.CharField(max_length=64, unique=True, null=True, blank=True)
    sebpay_transaction_id = models.CharField(max_length=100, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUS_PENDING, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_approved(self):
        return self.status in [self.STATUS_APPROVED, "reussi"]

    @property
    def is_pending(self):
        return self.status in [self.STATUS_PENDING, "en_attente"]

    @property
    def is_rejected(self):
        return self.status in [self.STATUS_REJECTED, "echoue"]

    def __str__(self):
        ref = self.external_reference or f"ID #{self.id}"
        return f"{self.user} - {self.amount} {self.currency} [{self.get_operator_display()}] - {self.status} ({ref})"