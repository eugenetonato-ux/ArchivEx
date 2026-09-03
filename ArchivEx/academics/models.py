import re
from django.core.exceptions import ValidationError
from django.db import models


def validate_academic_year_format(value):
    val = str(value).strip()
    pattern = r"^\d{4}-\d{4}$"
    if not re.match(pattern, val):
        raise ValidationError("L'année académique doit respecter le format YYYY-YYYY (ex: 2025-2026).")
    start_year, end_year = map(int, val.split("-"))
    if end_year != start_year + 1:
        raise ValidationError("L'année académique doit couvrir deux années consécutives (ex: 2025-2026).")


class School(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, blank=True, default="", help_text="Code unique de l'école (ex: ENEAM, FLASH)")
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="schools/", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name


class Level(models.Model):
    name = models.CharField(max_length=50)  # Licence 1, Licence 2, Licence 3, Master 1, etc.
    code = models.CharField(max_length=20, blank=True, default="")  # L1, L2, L3, M1
    school = models.ForeignKey(School, on_delete=models.CASCADE, null=True, blank=True, related_name="levels")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code", "name"]

    def __str__(self):
        if self.school:
            return f"{self.name} - {self.school.name}"
        return self.name


class Filiere(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="filieres")
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="filieres")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, blank=True, default="")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["school", "level", "name"]

    def __str__(self):
        return f"{self.name} ({self.level})"


class AcademicYear(models.Model):
    label = models.CharField(
        max_length=20,
        unique=True,
        validators=[validate_academic_year_format],
        help_text="Année académique au format YYYY-YYYY (ex: 2025-2026)",
    )

    class Meta:
        ordering = ["-label"]

    def clean(self):
        super().clean()
        if self.label:
            validate_academic_year_format(self.label)

    def __str__(self):
        return self.label


class Semester(models.Model):
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, related_name="semesters")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, null=True, blank=True)
    label = models.CharField(max_length=50)  # "Semestre 1"
    number = models.PositiveSmallIntegerField(default=1)  # 1, 2, 3, 4, 5, 6
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["filiere", "number"]

    def __str__(self):
        return f"{self.label} - {self.filiere}"


class Subject(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, blank=True, default="")  # ex. UE-MATH101
    description = models.TextField(blank=True, default="")
    image = models.ImageField(
        upload_to="subjects/",
        blank=True,
        null=True,
        verbose_name="Image de couverture",
        help_text="Image représentative de la matière / UE (format carré ou paysage recommandé)."
    )
    is_free = models.BooleanField(default=False)
    is_free_correction = models.BooleanField(default=False, help_text="Si vrai, les corrigés et résumés de cette UE sont gratuits pour tous les étudiants.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["semester", "name"]

    def __str__(self):
        return f"{self.code} - {self.name}" if self.code else self.name

    @property
    def exams_count(self):
        if hasattr(self, "_exams_count"):
            return self._exams_count
        return self.exams.filter(is_published=True).count()

    @exams_count.setter
    def exams_count(self, value):
        self._exams_count = value