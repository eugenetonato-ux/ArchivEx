from django.contrib import admin
from .models import Summary, Guide, Article


@admin.register(Summary)
class SummaryAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "access_type", "publication_status", "author", "created_at")
    list_filter = ("access_type", "publication_status", "subject__semester__filiere__school")
    search_fields = ("title", "subject__name", "introduction")
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("publication_status", "access_type")


@admin.register(Guide)
class GuideAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "access_type", "publication_status", "author", "created_at")
    list_filter = ("access_type", "publication_status", "subject__semester__filiere__school")
    search_fields = ("title", "subject__name", "introduction")
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("publication_status", "access_type")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "publication_status", "author", "created_at")
    list_filter = ("category", "publication_status", "target_school")
    search_fields = ("title", "summary", "content")
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("publication_status",)
