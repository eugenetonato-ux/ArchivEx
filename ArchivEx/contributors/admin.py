from django.contrib import admin
from .models import ContributorProfile


@admin.register(ContributorProfile)
class ContributorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "assigned_schools")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
    filter_horizontal = ("assigned_schools",)
