from django.contrib import admin
from .models import Exam


# ─── Actions bulk ─────────────────────────────────────────────────────────────

@admin.action(description="✅ Passer en GRATUIT (épreuve)")
def set_exam_free(modeladmin, request, queryset):
    queryset.update(is_free=True)


@admin.action(description="🔒 Passer en PREMIUM (épreuve)")
def set_exam_premium(modeladmin, request, queryset):
    queryset.update(is_free=False)


@admin.action(description="🌐 Publier les épreuves sélectionnées")
def publish_exams(modeladmin, request, queryset):
    queryset.update(is_published=True)


@admin.action(description="🚫 Dépublier les épreuves sélectionnées")
def unpublish_exams(modeladmin, request, queryset):
    queryset.update(is_published=False)


# ─── Admin principal ──────────────────────────────────────────────────────────

@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "subject",
        "filiere",
        "level",
        "exam_type",
        "year",
        "is_free",
        "is_published",
        "created_at",
    )
    list_filter = (
        "is_published",
        "is_free",
        "exam_type",
        "year",
        "filiere__school",
        "filiere",
        "level",
    )
    search_fields = ("title", "subject__name", "description")
    list_editable = ("is_published", "is_free")
    ordering = ("-created_at",)
    actions = [
        set_exam_free,
        set_exam_premium,
        publish_exams,
        unpublish_exams,
    ]
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Informations générales", {
            "fields": ("title", "subject", "semester", "filiere", "level", "academic_year", "exam_type", "year", "description"),
        }),
        ("Fichiers", {
            "fields": ("file", "correction_file", "summary_file", "summary", "cloud_file", "cloud_correction_file", "cloud_summary_file"),
        }),
        ("Contrôle d'accès", {
            "fields": ("is_free", "is_published"),
            "description": "⚠️ Corrections et résumés sont toujours Premium. Seule l'épreuve peut être gratuite.",
        }),
        ("Dates", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )