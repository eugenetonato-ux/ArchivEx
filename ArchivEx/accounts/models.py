from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
 """Utilisateur ArchivEx (étudiant ou administrateur)."""
 pass


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    school = models.ForeignKey("academics.School", on_delete=models.PROTECT)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
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
 