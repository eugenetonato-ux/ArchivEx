from django.db import models


class School(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="schools/", blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Level(models.Model):
    name = models.CharField(max_length=20)  # L1, L2, L3, M1, M2

    def __str__(self):
        return self.name


class Filiere(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="filieres")
    level = models.ForeignKey(Level, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.name} ({self.level})"


class AcademicYear(models.Model):
    label = models.CharField(max_length=20, unique=True)  # ex. "2026-2027"

    def __str__(self):
        return self.label


class Semester(models.Model):
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, related_name="semesters")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    label = models.CharField(max_length=50)  # "Semestre 1"

    def __str__(self):
        return f"{self.label} - {self.filiere}"


class Subject(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150)
    is_free = models.BooleanField(default=False)

    def __str__(self):
        return self.name