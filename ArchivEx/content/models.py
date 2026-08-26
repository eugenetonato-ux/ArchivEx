from django.conf import settings
from django.db import models
from django.utils.text import slugify

STATUS_CHOICES = [
    ("DRAFT", "Brouillon"),
    ("PENDING_REVIEW", "En attente de relecture"),
    ("PUBLISHED", "Publié"),
    ("ARCHIVED", "Archivé"),
]

ACCESS_CHOICES = [
    ("FREE", "Gratuit"),
    ("PREMIUM", "Premium"),
]


class Summary(models.Model):
    """Résumé de cours consultable directement sur le site web."""
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subject = models.ForeignKey("academics.Subject", on_delete=models.CASCADE, related_name="summaries")
    introduction = models.TextField(blank=True, help_text="Présentation succincte du résumé")
    content = models.TextField(help_text="Contenu rédigé du résumé (HTML ou texte enrichi)")
    file = models.FileField(upload_to="summaries_pdf/", blank=True, null=True, help_text="Version PDF optionnelle")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_summaries")
    access_type = models.CharField(max_length=10, choices=ACCESS_CHOICES, default="PREMIUM")
    publication_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "resume"
            self.slug = f"{base_slug}-{self.subject_id}"
        super().save(*args, **kwargs)

    @property
    def is_free(self):
        return self.access_type == "FREE"

    def __str__(self):
        return f"Résumé : {self.title} ({self.subject.name})"


class Guide(models.Model):
    """Guide méthodologique de matière consultable directement sur le web."""
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subject = models.ForeignKey("academics.Subject", on_delete=models.CASCADE, related_name="guides")

    introduction = models.TextField(blank=True, help_text="Présentation générale du guide")
    objectives = models.TextField(blank=True, help_text="Ce que l'étudiant doit maîtriser")
    how_to_study = models.TextField(blank=True, help_text="Méthode de travail recommandée")
    key_concepts = models.TextField(blank=True, help_text="Notions et concepts fondamentaux")
    working_with_past_papers = models.TextField(blank=True, help_text="Comment traiter les anciennes épreuves")
    common_mistakes = models.TextField(blank=True, help_text="Pièges courants à éviter")
    exam_strategy = models.TextField(blank=True, help_text="Stratégie pour le jour de l'examen")

    file = models.FileField(upload_to="guides_pdf/", blank=True, null=True, help_text="Fichier PDF optionnel")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_guides")
    access_type = models.CharField(max_length=10, choices=ACCESS_CHOICES, default="FREE")
    publication_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "guide"
            self.slug = f"{base_slug}-{self.subject_id}"
        super().save(*args, **kwargs)

    @property
    def is_free(self):
        return self.access_type == "FREE"

    def __str__(self):
        return f"Guide : {self.title} ({self.subject.name})"


class Article(models.Model):
    """Conseil pédagogique ou article général ou ciblé par école/filière/matière."""
    CATEGORY_CHOICES = [
        ("GENERAL", "Conseil Général"),
        ("METHODOLOGY", "Méthodologie de travail"),
        ("EXAM_PREP", "Préparation aux Examens"),
        ("ORIENTATION", "Orientation & Débouchés"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="GENERAL")

    target_school = models.ForeignKey("academics.School", on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")
    target_filiere = models.ForeignKey("academics.Filiere", on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")
    target_subject = models.ForeignKey("academics.Subject", on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")

    summary = models.TextField(blank=True, help_text="Bref résumé de l'article")
    content = models.TextField(help_text="Contenu rédigé de l'article")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_articles")
    publication_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "article"
            self.slug = base_slug
        super().save(*args, **kwargs)

    @property
    def is_free(self):
        return True

    def __str__(self):
        return f"Article : {self.title}"
