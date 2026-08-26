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

    # Active accesses (Legacy & V2)
    active_accesses = SemesterAccess.objects.filter(
        Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
    ).select_related("semester", "filiere", "level", "school").distinct()

    from subscriptions.models import UserSubscription
    from subscriptions.services import can_user_access
    from content.models import Summary, Guide, Article

    user_subscriptions = UserSubscription.objects.filter(
        user=request.user, is_active=True
    ).select_related("school", "filiere", "semester")

    # Favorites
    favorites = Favorite.objects.filter(user=request.user).select_related(
        "exam", "exam__subject", "exam__filiere"
    ).order_by("-created_at")[:6]

    # Personalized UEs & Content matching student's academic context
    semester_subjects_count = 0
    semester_exams_count = 0
    semester_summaries_count = 0
    semester_guides_count = 0

    if profile and profile.filiere:
        from academics.models import Semester, Subject
        active_semester = Semester.objects.filter(filiere=profile.filiere).first()
        if active_semester:
            semester_subjects_count = Subject.objects.filter(semester=active_semester).count()
            semester_exams_count = Exam.objects.filter(semester=active_semester, is_published=True).count()
            semester_summaries_count = Summary.objects.filter(subject__semester=active_semester, publication_status="PUBLISHED").count()
            semester_guides_count = Guide.objects.filter(subject__semester=active_semester, publication_status="PUBLISHED").count()

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
        exam.user_has_access = can_user_access(request.user, exam)

    # Summaries, Guides, Articles
    recent_summaries = Summary.objects.filter(publication_status="PUBLISHED").select_related("subject")[:4]
    for s in recent_summaries:
        s.user_has_access = can_user_access(request.user, s)

    recent_guides = Guide.objects.filter(publication_status="PUBLISHED").select_related("subject")[:4]
    for g in recent_guides:
        g.user_has_access = can_user_access(request.user, g)

    recent_articles = Article.objects.filter(publication_status="PUBLISHED")[:3]

    active_pass = active_accesses.exists() or user_subscriptions.filter(is_active=True).exists()

    context = {
        "profile": profile,
        "active_accesses": active_accesses,
        "user_subscriptions": user_subscriptions,
        "active_pass": active_pass,
        "active_semester": active_semester,
        "semester_subjects_count": semester_subjects_count,
        "semester_exams_count": semester_exams_count,
        "semester_summaries_count": semester_summaries_count,
        "semester_guides_count": semester_guides_count,
        "user_ues": user_ues,
        "favorites": favorites,
        "recent_exams": recent_exams,
        "recent_summaries": recent_summaries,
        "recent_guides": recent_guides,
        "recent_articles": recent_articles,
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


from django.http import JsonResponse
from academics.models import Level, Filiere

def api_levels_view(request):
    """API JSON retournant les niveaux d'études filtrés par école."""
    school_id = request.GET.get("school_id")
    levels = Level.objects.filter(is_active=True)
    if school_id:
        levels = levels.filter(Q(school_id=school_id) | Q(school__isnull=True))
    data = [{"id": l.id, "name": l.name, "code": l.code} for l in levels]
    return JsonResponse({"levels": data})


def api_filieres_view(request):
    """API JSON retournant les filières filtrées par école et niveau."""
    school_id = request.GET.get("school_id")
    level_id = request.GET.get("level_id")
    filieres = Filiere.objects.filter(is_active=True)
    if school_id:
        filieres = filieres.filter(school_id=school_id)
    if level_id:
        filieres = filieres.filter(level_id=level_id)
    data = [{"id": f.id, "name": f.name} for f in filieres]
    return JsonResponse({"filieres": data})


