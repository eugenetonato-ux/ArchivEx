from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, StudentProfile, Favorite


class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    can_delete = False
    verbose_name_plural = "Profil Étudiant"


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (StudentProfileInline,)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "date_joined")
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