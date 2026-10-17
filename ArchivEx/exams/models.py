from django.db import models
import os
import re
import unicodedata


def sanitize_upload_filename(filename):
    """
    Nettoie et sécurise le nom de fichier pour une compatibilité totale avec
    Supabase Storage S3, Linux, Windows et WhiteNoise.
    Supprime les accents, espaces et caractères spéciaux non-ASCII.
    Exemple: 'Corrigé Analyse mathématique (2025).pdf' -> 'Corrige_Analyse_mathematique_2025.pdf'
    """
    name, ext = os.path.splitext(filename)
    clean_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', clean_name)
    clean_name = re.sub(r'_+', '_', clean_name).strip('_')
    if not clean_name:
        clean_name = "document"
    clean_ext = ext.lower().strip()
    return f"{clean_name}{clean_ext}"


def exam_upload_to(instance, filename):
    """Organise les épreuves par année et semestre : exams/2024-2025/S1/fichier.pdf"""
    clean_filename = sanitize_upload_filename(filename)
    if instance.academic_year_id and hasattr(instance, 'academic_year') and instance.academic_year:
        year_label = str(instance.academic_year.label).replace('/', '-')
    elif instance.year:
        year_label = f"{instance.year - 1}-{instance.year}"
    else:
        year_label = "non-classe"
    year_label = re.sub(r'[^a-zA-Z0-9_\-]', '_', year_label)

    sem_label = "S1"
    if instance.semester_id and hasattr(instance, 'semester') and instance.semester:
        num = getattr(instance.semester, 'number', None)
        if num:
            sem_label = f"S{num}"
        else:
            lbl = getattr(instance.semester, 'label', '') or ""
            sem_label = lbl[:10] if lbl else "S1"
    sem_label = re.sub(r'[^a-zA-Z0-9_\-]', '_', sem_label)

    return f"exams/{year_label}/{sem_label}/{clean_filename}"


def correction_upload_to(instance, filename):
    """Organise les corrections par année et semestre : corrections/2024-2025/S1/fichier.pdf"""
    clean_filename = sanitize_upload_filename(filename)
    if instance.academic_year_id and hasattr(instance, 'academic_year') and instance.academic_year:
        year_label = str(instance.academic_year.label).replace('/', '-')
    elif instance.year:
        year_label = f"{instance.year - 1}-{instance.year}"
    else:
        year_label = "non-classe"
    year_label = re.sub(r'[^a-zA-Z0-9_\-]', '_', year_label)

    sem_label = "S1"
    if instance.semester_id and hasattr(instance, 'semester') and instance.semester:
        num = getattr(instance.semester, 'number', None)
        if num:
            sem_label = f"S{num}"
        else:
            lbl = getattr(instance.semester, 'label', '') or ""
            sem_label = lbl[:10] if lbl else "S1"
    sem_label = re.sub(r'[^a-zA-Z0-9_\-]', '_', sem_label)

    return f"corrections/{year_label}/{sem_label}/{clean_filename}"


def summary_upload_to(instance, filename):
    """Les résumés sont liés à l'UE, pas à une année académique.
    Chemin : summaries_pdf/fichier.pdf"""
    clean_filename = sanitize_upload_filename(filename)
    return f"summaries_pdf/{clean_filename}"


class Exam(models.Model):
    EXAM_TYPE_CHOICES = [
        ("examen", "Examen"),
        ("rattrapage", "Rattrapage"),
        ("devoir", "Devoir"),
        ("td", "TD"),
        ("tp", "TP"),
        ("concours", "Concours"),
        ("autre", "Autre"),
    ]

    title = models.CharField(max_length=200)
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="exams")
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT, related_name="exams")
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT, related_name="exams")

    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPE_CHOICES, db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to=exam_upload_to, help_text="Fichier PDF de l'épreuve")
    correction_file = models.FileField(upload_to=correction_upload_to, blank=True, null=True, help_text="Fichier PDF de la correction (optionnel)")
    summary_file = models.FileField(upload_to=summary_upload_to, blank=True, null=True, help_text="Fichier PDF du résumé/fiche (optionnel)")
    summary = models.ForeignKey("content.Summary", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams", help_text="Fiche résumé rédigée associée (optionnelle)")

    cloud_file = models.ForeignKey("content.CloudFile", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams_as_primary", help_text="Fichier Cloud de l'épreuve")
    cloud_correction_file = models.ForeignKey("content.CloudFile", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams_as_correction", help_text="Fichier Cloud de la correction")
    cloud_summary_file = models.ForeignKey("content.CloudFile", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams_as_summary", help_text="Fichier Cloud du résumé")

    is_free = models.BooleanField(default=True, db_index=True, help_text="Toutes les épreuves sont gratuites par défaut")
    is_free_correction = models.BooleanField(default=False, db_index=True)
    is_published = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.cloud_file and self.cloud_file.file and not self.file:
            self.file = self.cloud_file.file
        if self.cloud_correction_file and self.cloud_correction_file.file and not self.correction_file:
            self.correction_file = self.cloud_correction_file.file
        if self.cloud_summary_file and self.cloud_summary_file.file and not self.summary_file:
            self.summary_file = self.cloud_summary_file.file
        super().save(*args, **kwargs)


    @property
    def has_correction(self):
        return bool(self.correction_file or self.cloud_correction_file_id)

    @property
    def has_summary(self):
        if bool(self.summary_file or self.summary_id or self.cloud_summary_file_id):
            return True
        if hasattr(self, "_has_subject_summary"):
            return bool(self._has_subject_summary)
        if getattr(self, "subject_id", None):
            from content.models import Summary
            return Summary.objects.filter(subject_id=self.subject_id, publication_status="PUBLISHED").exists()
        return False

    @property
    def completeness_status(self):
        corr = self.has_correction
        summ = self.has_summary
        if corr and summ:
            return "COMPLETE"
        elif corr:
            return "EXAM_CORRECTION"
        elif summ:
            return "EXAM_SUMMARY"
        return "EXAM_ONLY"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("exams:detail", kwargs={"pk": self.pk})