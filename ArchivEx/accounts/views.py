import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.http import JsonResponse

from exams.models import Exam
from .forms import StudentRegistrationForm, StudentLoginForm, StudentProfileForm
from .models import StudentProfile, Favorite, SiteLog
from .utils import log_user_action
from payments.models import SemesterAccess

def register_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None):
            return redirect("contributors:admin_dashboard")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            log_user_action(request, "CONNECTION", f"Nouvelle inscription et connexion automatique de l'utilisateur : {user.username}")
            messages.success(request, f"Bienvenue {user.first_name} ! Ton compte a été créé avec succès.")
            return redirect("accounts:dashboard")
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous.")
    else:
        form = StudentRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})

def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None):
            return redirect("contributors:admin_dashboard")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = StudentLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            log_user_action(request, "CONNECTION", f"Connexion réussie de l'utilisateur : {user.username}")
            messages.success(request, f"Ravi de te revoir, {user.first_name or user.username} !")
            next_url = request.GET.get("next")
            from django.urls import reverse
            if not next_url or next_url == "/" or next_url == reverse("academics:home"):
                if user.is_staff or user.is_superuser or getattr(user, "contributor_profile", None):
                    return redirect("contributors:admin_dashboard")
                return redirect("accounts:dashboard")
            return redirect(next_url)
        else:
            messages.error(request, "Email ou mot de passe incorrect.")
    else:
        form = StudentLoginForm()

    return render(request, "accounts/login.html", {"form": form})

def logout_view(request):
    username = request.user.username if request.user.is_authenticated else "Anonyme"
    log_user_action(request, "CONNECTION", f"Déconnexion de l'utilisateur : {username}")
    logout(request)
    messages.info(request, "Tu es à présent déconnecté.")
    return redirect("academics:home")

@login_required
def dashboard_view(request):
    profile = getattr(request.user, "profile", None)
    if not profile:
        # Garantir qu'un profil étudiant existe pour tout utilisateur connecté (y compris administrateurs / staff qui consultent l'espace étudiant)
        from academics.models import Filiere, School, Level
        default_filiere = Filiere.objects.first()
        if default_filiere:
            default_school = default_filiere.school or School.objects.first()
            default_level = default_filiere.level or Level.objects.first()
            if default_school and default_level:
                profile, _ = StudentProfile.objects.get_or_create(
                    user=request.user,
                    defaults={
                        "school": default_school,
                        "filiere": default_filiere,
                        "level": default_level,
                    }
                )

    # Initialiser toutes les variables
    active_semester = None
    user_ues = []
    semester_subjects_count = 0
    semester_exams_count = 0
    semester_summaries_count = 0
    semester_guides_count = 0
    recent_exams = []
    recent_summaries = []
    recent_guides = []
    recent_articles = []

    # Active accesses (Legacy & V2)
    active_accesses = SemesterAccess.objects.filter(
        Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
    ).select_related("semester", "filiere", "level", "school").distinct()

    from subscriptions.models import UserSubscription
    from subscriptions.services import can_user_access
    from content.models import Summary, Guide, Article
    from academics.models import Semester, Subject, Filiere

    user_subscriptions = UserSubscription.objects.filter(
        user=request.user, is_active=True
    ).select_related("school", "filiere", "semester")

    # Favorites
    favorites = Favorite.objects.filter(user=request.user).select_related(
        "exam", "exam__subject", "exam__filiere"
    ).order_by("-created_at")[:6]

    # Filière active de l'étudiant
    filiere = None
    if profile and profile.filiere:
        filiere = profile.filiere
    else:
        active_access = active_accesses.first()
        if active_access and active_access.filiere:
            filiere = active_access.filiere
        else:
            filiere = Filiere.objects.first()

    available_semesters = Semester.objects.filter(filiere=filiere) if filiere else Semester.objects.all()
    selected_semester_id = request.GET.get("semester")
    if selected_semester_id:
        active_semester = available_semesters.filter(id=selected_semester_id).first()
    if not active_semester:
        active_access = active_accesses.first()
        if active_access and active_access.semester and active_access.semester in available_semesters:
            active_semester = active_access.semester
        else:
            active_semester = available_semesters.first()

    # Calcul des métriques réelles depuis la base de données
    if active_semester:
        semester_subjects_count = Subject.objects.filter(semester=active_semester, is_active=True).count()
        semester_exams_count = Exam.objects.filter(semester=active_semester, is_published=True).count()
        semester_summaries_count = Summary.objects.filter(subject__semester=active_semester, publication_status="PUBLISHED").count()
        semester_guides_count = Guide.objects.filter(subject__semester=active_semester, publication_status="PUBLISHED").count()

        user_ues = Subject.objects.filter(semester=active_semester, is_active=True).annotate(
            exams_num=Count("exams", filter=Q(exams__is_published=True))
        )
        recent_exams = Exam.objects.filter(
            semester=active_semester, is_published=True
        ).select_related("subject", "semester", "filiere")[:6]
    elif filiere:
        semester_subjects_count = Subject.objects.filter(semester__filiere=filiere, is_active=True).count()
        semester_exams_count = Exam.objects.filter(filiere=filiere, is_published=True).count()
        semester_summaries_count = Summary.objects.filter(subject__semester__filiere=filiere, publication_status="PUBLISHED").count()
        semester_guides_count = Guide.objects.filter(subject__semester__filiere=filiere, publication_status="PUBLISHED").count()

        user_ues = Subject.objects.filter(semester__filiere=filiere, is_active=True).annotate(
            exams_num=Count("exams", filter=Q(exams__is_published=True))
        )
        recent_exams = Exam.objects.filter(
            filiere=filiere, is_published=True
        ).select_related("subject", "semester", "filiere")[:6]
    else:
        semester_subjects_count = Subject.objects.filter(is_active=True).count()
        semester_exams_count = Exam.objects.filter(is_published=True).count()
        semester_summaries_count = Summary.objects.filter(publication_status="PUBLISHED").count()
        semester_guides_count = Guide.objects.filter(publication_status="PUBLISHED").count()

        user_ues = Subject.objects.filter(is_active=True).annotate(
            exams_num=Count("exams", filter=Q(exams__is_published=True))
        )[:8]
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

    # Chart data: distribution des documents par filière (spécialité académique)
    student_school = profile.school if profile and profile.school else None
    filieres_qs = Filiere.objects.filter(school=student_school) if student_school else Filiere.objects.all()
    filieres_qs = filieres_qs.annotate(
        exams_cnt=Count('exams', filter=Q(exams__is_published=True), distinct=True),
        summaries_cnt=Count('semesters__subjects__summaries', filter=Q(semesters__subjects__summaries__publication_status="PUBLISHED"), distinct=True),
        guides_cnt=Count('semesters__subjects__guides', filter=Q(semesters__subjects__guides__publication_status="PUBLISHED"), distinct=True)
    )

    chart_labels = []
    chart_exams = []
    chart_summaries = []
    chart_guides = []
    chart_totals = []

    for f in filieres_qs:
        chart_labels.append(f.name)
        chart_exams.append(f.exams_cnt)
        chart_summaries.append(f.summaries_cnt)
        chart_guides.append(f.guides_cnt)
        chart_totals.append(f.exams_cnt + f.summaries_cnt + f.guides_cnt)

    filiere_chart_json = json.dumps({
        "labels": chart_labels,
        "exams": chart_exams,
        "summaries": chart_summaries,
        "guides": chart_guides,
        "totals": chart_totals,
    }, ensure_ascii=False)

    context = {
        "profile": profile,
        "filiere": filiere,
        "available_semesters": available_semesters,
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
        "filiere_chart_json": filiere_chart_json,
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
        Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
    ).select_related("semester", "filiere", "level", "school").distinct()

    context = {
        "profile": profile,
        "form": form,
        "active_accesses": active_accesses,
    }
    return render(request, "dashboard/profil.html", context)

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

import json
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def api_log_click_view(request):
    """API JSON pour enregistrer un événement de clic depuis l'interface publique."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            button_label = data.get("label", "Bouton inconnu")
            element_id = data.get("element_id", "")
            page_title = data.get("page_title", "")
            
            desc = f"Clic public : '{button_label}'"
            if element_id:
                desc += f" (ID: {element_id})"
            if page_title:
                desc += f" sur la page [{page_title}]"
                
            log_user_action(request, "CLICK", desc)
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
