from django.contrib import admin
from .models import Exam


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "filiere", "level", "exam_type", "year", "is_free", "is_published", "created_at")
    list_filter = ("is_published", "is_free", "exam_type", "year", "filiere__school", "filiere", "level")
    search_fields = ("title", "subject__name", "description")
    list_editable = ("is_published", "is_free")