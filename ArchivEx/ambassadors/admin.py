from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import Ambassador, AmbassadorSale


@admin.register(Ambassador)
class AmbassadorAdmin(admin.ModelAdmin):
    list_display = [
        "full_name",
        "phone_number",
        "code",
        "sales_count_display",
        "total_earnings_display",
        "pending_payout_display",
        "is_active",
        "dashboard_link_display",
        "created_at",
    ]
    list_filter = ["is_active", "payout_operator", "created_at"]
    search_fields = ["first_name", "last_name", "phone_number", "code", "payout_phone"]
    readonly_fields = [
        "access_token",
        "sales_count_display",
        "total_earnings_display",
        "pending_payout_display",
        "paid_payout_display",
        "dashboard_link_display",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        ("Identité de l'ambassadeur", {
            "fields": ("first_name", "last_name", "phone_number", "user", "notes")
        }),
        ("Code Promo & Configuration", {
            "fields": ("code", "discount_amount", "commission_per_sale", "is_active")
        }),
        ("Lien privé d'accès (À envoyer à l'étudiant)", {
            "fields": ("dashboard_link_display", "access_token")
        }),
        ("Coordonnées de versement (Mobile Money)", {
            "fields": ("payout_operator", "payout_phone", "payout_name")
        }),
        ("Statistiques financières", {
            "fields": ("sales_count_display", "total_earnings_display", "pending_payout_display", "paid_payout_display")
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def sales_count_display(self, obj):
        return f"{obj.sales_count} vente(s)"
    sales_count_display.short_description = "Ventes validées"

    def total_earnings_display(self, obj):
        return f"{obj.total_earnings:,} FCFA".replace(",", " ")
    total_earnings_display.short_description = "Gains totaux"

    def pending_payout_display(self, obj):
        pending = obj.pending_payout
        color = "#e11d48" if pending > 0 else "#16a34a"
        return format_html('<span style="color: {}; font-weight: bold;">{} FCFA</span>', color, f"{pending:,}".replace(",", " "))
    pending_payout_display.short_description = "À reverser"

    def paid_payout_display(self, obj):
        return f"{obj.paid_payout:,} FCFA".replace(",", " ")
    paid_payout_display.short_description = "Déjà reversé"

    def dashboard_link_display(self, obj):
        if not obj.access_token:
            return "-"
        url = reverse("ambassadors:dashboard", kwargs={"token": obj.access_token})
        return format_html(
            '<a href="{}" target="_blank" style="display:inline-block; padding:4px 8px; background:#2563EB; color:#fff; border-radius:6px; text-decoration:none; font-weight:bold; font-size:11px;">Ouvrir / Copier l\'Espace Ambassadeur &rarr;</a>',
            url
        )
    dashboard_link_display.short_description = "Lien Privé Ambassadeur"

    actions = ["mark_all_pending_as_paid"]

    @admin.action(description="Marquer toutes les commissions en attente comme PAYÉES (reversées)")
    def mark_all_pending_as_paid(self, request, queryset):
        count = 0
        now = timezone.now()
        for amb in queryset:
            pending_sales = amb.sales.filter(status="APPROVED")
            count += pending_sales.update(status="PAID_OUT", paid_out_at=now)
        self.message_user(request, f"{count} commission(s) marquée(s) comme reversée(s) avec succès.")


@admin.register(AmbassadorSale)
class AmbassadorSaleAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "ambassador",
        "payment_user",
        "commission_amount_display",
        "discount_given_display",
        "status",
        "paid_out_at",
    ]
    list_filter = ["status", "created_at", "ambassador"]
    search_fields = ["ambassador__code", "ambassador__first_name", "ambassador__last_name", "payment__user__username"]
    readonly_fields = ["created_at"]

    def payment_user(self, obj):
        return obj.payment.user.username if obj.payment and obj.payment.user else "-"
    payment_user.short_description = "Acheteur (Filleul)"

    def commission_amount_display(self, obj):
        return f"{obj.commission_amount} FCFA"
    commission_amount_display.short_description = "Commission"

    def discount_given_display(self, obj):
        return f"-{obj.discount_given} FCFA"
    discount_given_display.short_description = "Réduction"
