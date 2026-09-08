from django.contrib import admin
from .models import SemesterAccess, Payment


@admin.register(SemesterAccess)
class SemesterAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "filiere", "semester", "activated_at")
    list_filter = ("school", "level", "filiere", "semester")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("activated_at",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "external_reference",
        "user",
        "semester",
        "amount",
        "currency",
        "status",
        "chariow_sale_id",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "currency", "created_at", "paid_at")
    search_fields = (
        "user__username",
        "user__email",
        "external_reference",
        "chariow_sale_id",
        "phone_number",
    )
    readonly_fields = (
        "external_reference",
        "chariow_sale_id",
        "chariow_checkout_url",
        "created_at",
        "updated_at",
    )