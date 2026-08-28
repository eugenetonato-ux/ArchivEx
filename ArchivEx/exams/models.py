from django.db import models


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
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPE_CHOICES)
    year = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="exams/", help_text="Fichier PDF de l'épreuve")
    correction_file = models.FileField(upload_to="corrections/", blank=True, null=True, help_text="Fichier PDF de la correction (optionnel)")
    summary_file = models.FileField(upload_to="summaries_pdf/", blank=True, null=True, help_text="Fichier PDF du résumé/fiche (optionnel)")
    summary = models.ForeignKey("content.Summary", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams", help_text="Fiche résumé rédigée associée (optionnelle)")

    cloud_file = models.ForeignKey("content.CloudFile", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams_as_primary", help_text="Fichier Cloud de l'épreuve")
    cloud_correction_file = models.ForeignKey("content.CloudFile", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams_as_correction", help_text="Fichier Cloud de la correction")
    cloud_summary_file = models.ForeignKey("content.CloudFile", on_delete=models.SET_NULL, blank=True, null=True, related_name="exams_as_summary", help_text="Fichier Cloud du résumé")

    is_free = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
        return bool(self.correction_file)

    @property
    def has_summary(self):
        return bool(self.summary_file or self.summary)

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