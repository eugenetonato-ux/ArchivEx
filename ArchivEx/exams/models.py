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
    file = models.FileField(upload_to="exams/")
    is_free = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title