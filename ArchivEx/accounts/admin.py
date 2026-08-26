from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, StudentProfile, Favorite
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


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (StudentProfileInline, ContributorProfileInline)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_superuser", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")


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