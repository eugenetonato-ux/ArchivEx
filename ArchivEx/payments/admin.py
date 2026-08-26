from django.contrib import admin
from .models import SemesterAccess, Payment


@admin.register(SemesterAccess)
class SemesterAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "filiere", "semester", "activated_at")
    list_filter = ("school", "level", "filiere", "semester")
    search_fields = ("user__username", "user__email")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "semester_access", "amount", "status", "paid_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "user__email")