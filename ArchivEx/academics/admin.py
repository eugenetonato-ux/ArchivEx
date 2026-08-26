from django.contrib import admin
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
    list_display = ("name", "semester", "is_free")
    list_filter = ("is_free", "semester__filiere")
    search_fields = ("name",)