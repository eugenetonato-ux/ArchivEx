from django.contrib import admin
from .models import SubscriptionPlan, UserSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "scope", "price", "duration_days", "is_active", "created_at")
    list_filter = ("scope", "is_active")
    search_fields = ("name", "code")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "school", "filiere", "semester", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "school", "filiere")
    search_fields = ("user__username", "user__email")
