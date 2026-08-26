from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from exams.models import Exam
from .forms import StudentRegistrationForm, StudentLoginForm, StudentProfileForm
from .models import StudentProfile, Favorite
from payments.models import SemesterAccess
from django.db.models import Q, Count


def register_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Bienvenue {user.first_name} ! Ton compte a été créé avec succès.")
            return redirect("accounts:dashboard")
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous.")
    else:
        form = StudentRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = StudentLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Ravi de te revoir, {user.first_name or user.username} !")
            next_url = request.GET.get("next") or "accounts:dashboard"
            return redirect(next_url)
        else:
            messages.error(request, "Email ou mot de passe incorrect.")
    else:
        form = StudentLoginForm()

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "Tu es à présent déconnecté.")
    return redirect("academics:home")


@login_required
def dashboard_view(request):
    profile = getattr(request.user, "profile", None)
    
    # Active accesses
    active_accesses = SemesterAccess.objects.filter(
        Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
    ).select_related("semester", "filiere", "level", "school").distinct()
    user_accesses = set(active_accesses.values_list("semester_id", flat=True))

    # Favorites
    favorites = Favorite.objects.filter(user=request.user).select_related(
        "exam", "exam__subject", "exam__filiere"
    ).order_by("-created_at")[:6]

    # Personalized UEs & Recent Exams matching student's academic context
    user_ues = []
    active_semester = None
    if profile and profile.filiere:
        from academics.models import Semester, Subject
        active_semester = Semester.objects.filter(filiere=profile.filiere).first()
        if active_semester:
            user_ues = Subject.objects.filter(semester=active_semester).annotate(
                exams_num=Count("exams")
            )[:6]
        recent_exams = Exam.objects.filter(
            filiere=profile.filiere, is_published=True
        ).select_related("subject", "semester", "filiere")[:6]
    else:
        recent_exams = Exam.objects.filter(
            is_published=True
        ).select_related("subject", "semester", "filiere")[:6]

    for exam in recent_exams:
        exam.user_has_access = exam.is_free or (exam.semester_id in user_accesses)

    context = {
        "profile": profile,
        "active_accesses": active_accesses,
        "active_semester": active_semester,
        "user_ues": user_ues,
        "favorites": favorites,
        "recent_exams": recent_exams,
    }
    return render(request, "dashboard/dashboard.html", context)


@login_required
def favorites_list_view(request):
    user_accesses = set(
        SemesterAccess.objects.filter(
            Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
        ).values_list("semester_id", flat=True)
    )
    favorites = Favorite.objects.filter(user=request.user).select_related(
        "exam", "exam__subject", "exam__semester", "exam__filiere", "exam__level", "exam__academic_year"
    ).order_by("-created_at")

    for fav in favorites:
        fav.exam.user_has_access = fav.exam.is_free or (fav.exam.semester_id in user_accesses)

    return render(request, "dashboard/favoris.html", {"favorites": favorites})


@login_required
def profile_view(request):
    profile = getattr(request.user, "profile", None)

    if request.method == "POST":
        user = request.user
        if "first_name" in request.POST:
            user.first_name = request.POST.get("first_name", "").strip()
        if "last_name" in request.POST:
            user.last_name = request.POST.get("last_name", "").strip()
        user.save()

        if profile:
            form = StudentProfileForm(request.POST, request.FILES, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Ton profil a été mis à jour avec succès !")
                return redirect("accounts:profile")
            else:
                messages.error(request, "Veuillez vérifier les informations saisies.")
        else:
            form = StudentProfileForm(request.POST, request.FILES)
            if form.is_valid():
                prof = form.save(commit=False)
                prof.user = user
                prof.save()
                messages.success(request, "Profil créé avec succès !")
                return redirect("accounts:profile")
            else:
                messages.error(request, "Veuillez vérifier les informations saisies.")
    else:
        form = StudentProfileForm(instance=profile) if profile else StudentProfileForm(initial={
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
        })

    active_accesses = SemesterAccess.objects.filter(
        Q(user=request.user) & (Q(activated_at__isnull=False) |Q (payments__status="reussi"))
    ).select_related("semester", "filiere", "level", "school").distinct()

    context = {
        "profile": profile,
        "form": form,
        "active_accesses": active_accesses,
    }
    return render(request, "dashboard/profil.html", context)

