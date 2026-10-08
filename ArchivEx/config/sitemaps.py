from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from academics.models import School, Filiere, Semester, Subject
from exams.models import Exam
from content.models import Summary, Guide, Article


class StaticViewSitemap(Sitemap):
    """Pages statiques et points d'entrée principaux d'ArchivEx."""
    priority = 1.0
    changefreq = "daily"

    def items(self):
        return [
            "academics:home",
            "exams:liste",
            "exams:free_liste",
            "exams:premium_liste",
            "content:summary_list",
            "content:guide_list",
            "content:article_list",
            "content:student_guide",
            "academics:about",
            "academics:filieres",
        ]

    def location(self, item):
        return reverse(item)


class SchoolSitemap(Sitemap):
    """Écoles et universités du Bénin."""
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        return School.objects.filter(is_active=True).order_by("name")

    def lastmod(self, obj):
        return obj.updated_at or obj.created_at


class FiliereSitemap(Sitemap):
    """Filières d'études supérieures."""
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        return Filiere.objects.filter(is_active=True).select_related("school", "level").order_by("school__name", "name")

    def lastmod(self, obj):
        return obj.updated_at or obj.created_at


class SemesterSitemap(Sitemap):
    """Semestres académiques par filière."""
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Semester.objects.filter(is_active=True).select_related("filiere", "filiere__school").order_by("filiere_id", "number")

    def lastmod(self, obj):
        # Utilise l'épreuve la plus récente du semestre comme proxy de fraîcheur
        latest_exam = obj.exams.filter(is_published=True).order_by("-updated_at").first()
        if latest_exam and latest_exam.updated_at:
            return latest_exam.updated_at
        return None


class SubjectSitemap(Sitemap):
    """Unités d'enseignement et matières."""
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Subject.objects.filter(is_active=True).select_related("semester", "semester__filiere").order_by("semester_id", "name")

    def lastmod(self, obj):
        latest_exam = obj.exams.filter(is_published=True).order_by("-updated_at").first()
        if latest_exam and latest_exam.updated_at:
            return latest_exam.updated_at
        return None


class ExamSitemap(Sitemap):
    """Épreuves et sujets d'examen publiés."""
    changefreq = "weekly"
    priority = 0.9

    def items(self):
        return Exam.objects.filter(is_published=True).select_related("subject", "filiere", "semester").order_by("-updated_at", "-id")

    def lastmod(self, obj):
        return obj.updated_at or obj.created_at


class SummarySitemap(Sitemap):
    """Fiches et résumés de cours publiés."""
    changefreq = "weekly"
    priority = 0.85

    def items(self):
        return Summary.objects.filter(publication_status="PUBLISHED").select_related("subject").order_by("-updated_at", "-id")

    def lastmod(self, obj):
        return obj.updated_at or obj.created_at


class GuideSitemap(Sitemap):
    """Guides méthodologiques publiés."""
    changefreq = "monthly"
    priority = 0.75

    def items(self):
        return Guide.objects.filter(publication_status="PUBLISHED").select_related("subject").order_by("-updated_at", "-id")

    def lastmod(self, obj):
        return obj.updated_at or obj.created_at


class ArticleSitemap(Sitemap):
    """Conseils pédagogiques et articles publiés."""
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return Article.objects.filter(publication_status="PUBLISHED").order_by("-updated_at", "-id")

    def lastmod(self, obj):
        return obj.updated_at or obj.created_at
