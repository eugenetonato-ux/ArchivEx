from django.contrib import admin
from django.utils.html import format_html
from .models import School, Level, Filiere, AcademicYear, Semester, Subject


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Filiere)
class FiliereAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "level")
    list_filter = ("school", "level")
    search_fields = ("name",)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("label",)


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("label", "filiere", "academic_year")
    list_filter = ("filiere__school", "filiere", "academic_year")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("image_thumbnail", "name", "code", "semester", "is_free", "exams_count_display")
    list_display_links = ("image_thumbnail", "name")
    list_filter = ("is_free", "semester__filiere__school", "semester__filiere", "semester")
    search_fields = ("name", "code")
    readonly_fields = ("image_preview_large",)
    fields = ("semester", "name", "code", "image", "image_preview_large", "description", "is_free", "is_free_correction", "is_active")

    def image_thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 38px; height: 38px; object-fit: cover; border-radius: 8px; border: 1px solid #e2e8f0;" />',
                obj.image.url
            )
        return format_html(
            '<span style="display:inline-block; width: 38px; height: 38px; line-height: 38px; text-align: center; background: #e2e8f0; color: #64748b; border-radius: 8px; font-size: 10px; font-weight: bold;">SANS</span>'
        )
    image_thumbnail.short_description = "Image"

    def image_preview_large(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-width: 260px; max-height: 180px; object-fit: cover; border-radius: 12px; border: 1px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);" />',
                obj.image.url
            )
        return "Aucune image définie pour cette matière."
    image_preview_large.short_description = "Aperçu de l'image"

    def exams_count_display(self, obj):
        count = obj.exams_count
        return f"{count} épreuve{'s' if count > 1 else ''}"
    exams_count_display.short_description = "Épreuves publiées"