from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, StudentProfile, Favorite, SiteLog, UserDevice, DeviceRevocationLog
from contributors.models import ContributorProfile


class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    can_delete = False
    verbose_name_plural = "Profil Étudiant"


class ContributorProfileInline(admin.StackedInline):
    model = ContributorProfile
    can_delete = True
    verbose_name_plural = "Profil Administrateur / Staff"
    filter_horizontal = ("assigned_schools",)
    extra = 0


class UserDeviceInline(admin.TabularInline):
    model = UserDevice
    extra = 0
    verbose_name_plural = "Appareils autorisés enregistrés (Max 2)"
    readonly_fields = ("created_at", "last_login")
    fields = ("device_name", "ip_address", "last_login", "created_at")
    can_delete = True


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (StudentProfileInline, ContributorProfileInline, UserDeviceInline)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_superuser", "is_active", "devices_count", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")
    actions = ["reactivate_and_reset_devices", "reset_devices_only"]

    @admin.display(description="Appareils")
    def devices_count(self, obj):
        count = obj.devices.count()
        return f"{count}/2"

    @admin.action(description="🔓 Réactiver le(s) compte(s) et réinitialiser les appareils")
    def reactivate_and_reset_devices(self, request, queryset):
        count = 0
        for user in queryset:
            user.is_active = True
            user.save(update_fields=["is_active"])
            user.devices.all().delete()
            SiteLog.objects.create(
                user=request.user,
                action_type="SECURITY_UNLOCK",
                description=f"Compte {user.username} réactivé et appareils réinitialisés par l'admin {request.user.username} via Django Admin."
            )
            count += 1
        self.message_user(request, f"{count} compte(s) réactivé(s) et appareils réinitialisés avec succès.")

    @admin.action(description="📱 Réinitialiser uniquement les appareils (vider quota)")
    def reset_devices_only(self, request, queryset):
        count = 0
        for user in queryset:
            dev_count = user.devices.count()
            user.devices.all().delete()
            count += dev_count
        self.message_user(request, f"{count} appareil(s) supprimé(s) pour les utilisateurs sélectionnés.")


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "ip_address", "last_login", "created_at")
    list_filter = ("created_at", "last_login")
    search_fields = ("user__username", "user__email", "device_name", "ip_address")
    readonly_fields = ("created_at", "last_login")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "level", "filiere", "created_at")
    list_filter = ("school", "level", "filiere")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "exam", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "exam__title")


@admin.register(SiteLog)
class SiteLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action_type", "user", "ip_address", "path")
    list_filter = ("action_type", "created_at")
    search_fields = ("description", "user__username", "path", "ip_address")
    readonly_fields = ("created_at",)
    actions = ["clear_selected_logs"]

    @admin.action(description="Supprimer les logs sélectionnés")
    def clear_selected_logs(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} entrées de journal ont été supprimées.")