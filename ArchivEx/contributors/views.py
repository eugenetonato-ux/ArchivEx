from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.http import JsonResponse

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from exams.models import Exam
from content.models import Summary, Guide, Article
from accounts.models import StudentProfile
from payments.models import SemesterAccess, Payment
from notifications.services import notify_target_students

from .decorators import contributor_required, get_active_academic_context, is_user_contributor
from .permissions import check_school_permission
from .forms import (
    ContextSelectForm,
    ExamAdminForm,
    SummaryAdminForm,
    GuideAdminForm,
    ArticleAdminForm,
    SubjectAdminForm,
    NotificationAdminForm,
)

User = get_user_model()


# ==========================================
# AUTHENTIFICATION & ESPACE CONNEXION STAFF
# ==========================================

def admin_login_view(request):
    """
    Page de connexion dédiée à l'espace d'administration et au personnel staff.
    """
    if request.user.is_authenticated:
        if is_user_contributor(request.user):
            next_url = request.GET.get("next") or request.POST.get("next") or "/administration/"
            return redirect(next_url)
        else:
            messages.warning(request, "Votre compte n'a pas les privilèges d'accès à l'administration.")

    error = None
    next_url = request.GET.get("next") or request.POST.get("next", "")

    if request.method == "POST":
        username_input = request.POST.get("username", "").strip()
        password_input = request.POST.get("password", "").strip()

        if not username_input or not password_input:
            error = "Veuillez remplir tous les champs de connexion."
        else:
            # Tentative par nom d'utilisateur ou par email
            user = authenticate(request, username=username_input, password=password_input)
            if user is None and "@" in username_input:
                user_obj = User.objects.filter(email__iexact=username_input).first()
                if user_obj:
                    user = authenticate(request, username=user_obj.username, password=password_input)

            if user is not None:
                if is_user_contributor(user):
                    login(request, user)
                    messages.success(request, f"Bienvenue dans l'espace administration, {user.first_name or user.username} !")
                    target_url = request.POST.get("next") or request.GET.get("next") or "/administration/"
                    return redirect(target_url)
                else:
                    error = "Accès refusé : ce compte ne dispose pas des autorisations staff/administrateur."
            else:
                error = "Nom d'utilisateur ou mot de passe incorrect."

    context = {
        "error": error,
        "next": next_url,
        "username": request.POST.get("username", ""),
    }
    return render(request, "contributors/login.html", context)


def admin_logout_view(request):
    """
    Déconnecte le membre staff de la session d'administration.
    """
    logout(request)
    messages.info(request, "Vous avez été déconnecté avec succès de l'espace administration.")
    return redirect("contributors:admin_login")


def get_filieres_by_school_api(request):
    """
    API JSON retournant la liste des filières pour une université spécifique (pour mises à jour dynamiques AJAX).
    """
    school_id = request.GET.get("school_id")
    if not school_id:
        return JsonResponse({"filieres": []})

    if not check_school_permission(request.user, school_id):
        return JsonResponse({"error": "Non autorisé"}, status=403)

    filieres = Filiere.objects.filter(school_id=school_id).values("id", "name", "code")
    return JsonResponse({"filieres": list(filieres)})


@contributor_required
def admin_dashboard_view(request):
    """Tableau de bord privé d'administration ArchivEx V2."""
    active_school, active_filiere = get_active_academic_context(request)

    # Context-aware metrics
    if active_school:
        students_count = StudentProfile.objects.filter(school=active_school).count()
        exams_count = Exam.objects.filter(filiere__school=active_school).count()
        published_exams = Exam.objects.filter(filiere__school=active_school, is_published=True).count()
        summaries_count = Summary.objects.filter(subject__semester__filiere__school=active_school).count()
        guides_count = Guide.objects.filter(subject__semester__filiere__school=active_school).count()
        recent_exams = Exam.objects.filter(filiere__school=active_school).select_related("subject", "semester", "filiere").order_by("-created_at")[:6]
    else:
        students_count = StudentProfile.objects.count()
        exams_count = Exam.objects.count()
        published_exams = Exam.objects.filter(is_published=True).count()
        summaries_count = Summary.objects.count()
        guides_count = Guide.objects.count()
        recent_exams = Exam.objects.select_related("subject", "semester", "filiere").order_by("-created_at")[:6]

    articles_count = Article.objects.count()
    active_pass_count = SemesterAccess.objects.filter(activated_at__isnull=False).count()
    recent_summaries = Summary.objects.select_related("subject").order_by("-created_at")[:5]

    available_schools = School.objects.filter(is_active=True)
    if not request.user.is_superuser:
        profile = getattr(request.user, "contributor_profile", None)
        if profile and profile.assigned_schools.exists():
            available_schools = profile.assigned_schools.filter(is_active=True)

    available_filieres = Filiere.objects.filter(school=active_school) if active_school else Filiere.objects.none()

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "available_schools": available_schools,
        "available_filieres": available_filieres,
        "students_count": students_count,
        "exams_count": exams_count,
        "published_exams": published_exams,
        "summaries_count": summaries_count,
        "guides_count": guides_count,
        "articles_count": articles_count,
        "active_pass_count": active_pass_count,
        "recent_exams": recent_exams,
        "recent_summaries": recent_summaries,
    }
    return render(request, "contributors/dashboard.html", context)


@contributor_required
def set_context_view(request):
    """Change le contexte académique actif (Université + Filière) dans la session."""
    school_id = request.GET.get("school_id") or request.POST.get("school_id")
    filiere_id = request.GET.get("filiere_id") or request.POST.get("filiere_id")

    if school_id:
        if school_id == "all":
            request.session["admin_active_school_id"] = None
            request.session["admin_active_filiere_id"] = None
            messages.info(request, "Contexte réinitialisé : Toutes les universités")
        else:
            school = get_object_or_404(School, pk=school_id)
            if not check_school_permission(request.user, school):
                raise PermissionDenied("Vous n'êtes pas autorisé à gérer le contenu de cette université.")
            
            # Changement d'école
            old_school_id = request.session.get("admin_active_school_id")
            request.session["admin_active_school_id"] = school.id

            if filiere_id:
                if filiere_id == "all":
                    request.session["admin_active_filiere_id"] = None
                else:
                    filiere = Filiere.objects.filter(pk=filiere_id, school=school).first()
                    request.session["admin_active_filiere_id"] = filiere.id if filiere else None
            elif old_school_id != school.id:
                # Si l'école a changé sans filière explicite, sélectionner la 1ère filière ou None
                first_filiere = Filiere.objects.filter(school=school).first()
                request.session["admin_active_filiere_id"] = first_filiere.id if first_filiere else None

            filiere_name = ""
            if request.session.get("admin_active_filiere_id"):
                f = Filiere.objects.filter(pk=request.session.get("admin_active_filiere_id")).first()
                if f:
                    filiere_name = f" — {f.name}"

            messages.success(request, f"Contexte actif : {school.name}{filiere_name}")

    elif filiere_id:
        if filiere_id == "all":
            request.session["admin_active_filiere_id"] = None
            messages.info(request, "Filière réinitialisée : Toutes les filières")
        else:
            active_school_id = request.session.get("admin_active_school_id")
            filiere = Filiere.objects.filter(pk=filiere_id).first()
            if filiere:
                if not active_school_id or filiere.school_id == active_school_id:
                    request.session["admin_active_school_id"] = filiere.school_id
                    request.session["admin_active_filiere_id"] = filiere.id
                    messages.success(request, f"Filière active : {filiere.name} ({filiere.school.name})")

    next_url = request.META.get("HTTP_REFERER") or "/administration/"
    return redirect(next_url)



# ==========================================
# 1. ÉPREUVES (EXAMS) MANAGEMENT
# ==========================================

@contributor_required
def exam_list_view(request):
    """Liste et recherche des épreuves dans le contexte actif."""
    active_school, active_filiere = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()

    qs = Exam.objects.select_related("subject", "semester", "filiere", "filiere__school")
    if active_school:
        qs = qs.filter(filiere__school=active_school)
    if active_filiere:
        qs = qs.filter(filiere=active_filiere)

    if q:
        from academics.search import remove_accents
        q_u = remove_accents(q)
        qs = qs.filter(
            Q(title__icontains=q) | Q(title__icontains=q_u) | Q(subject__name__icontains=q) | Q(year__icontains=q)
        )

    exams = qs.order_by("-created_at")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "exams": exams,
        "q": q,
    }
    return render(request, "contributors/exams/list.html", context)


@contributor_required
def exam_create_view(request):
    """Ajouter une épreuve d'examen avec héritage du contexte actif."""
    active_school, active_filiere = get_active_academic_context(request)
    if active_school and not check_school_permission(request.user, active_school):
        raise PermissionDenied("Vous n'êtes pas autorisé à ajouter une épreuve pour cette université.")

    if request.method == "POST":
        form = ExamAdminForm(request.POST, request.FILES, active_filiere=active_filiere)
        if form.is_valid():
            exam = form.save(commit=False)
            if active_filiere:
                exam.filiere = active_filiere
                exam.level = active_filiere.level
            elif form.cleaned_data.get("semester"):
                exam.filiere = form.cleaned_data["semester"].filiere
                exam.level = form.cleaned_data["semester"].filiere.level

            if not getattr(exam, "academic_year_id", None):
                if exam.semester and hasattr(exam.semester, "academic_year"):
                    exam.academic_year = exam.semester.academic_year
                else:
                    exam.academic_year = AcademicYear.objects.first()

            exam.is_free = form.cleaned_data["is_free"]
            exam.is_published = form.cleaned_data["is_published"]
            exam.save()

            status_str = "publiée" if exam.is_published else "enregistrée en brouillon"
            messages.success(request, f"Épreuve « {exam.title} » {status_str} avec succès.")
            return redirect("contributors:exam_list")
    else:
        form = ExamAdminForm(active_filiere=active_filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "is_create": True,
    }
    return render(request, "contributors/exams/form.html", context)


@contributor_required
def exam_edit_view(request, pk):
    """Modifier une épreuve existante."""
    exam = get_object_or_404(Exam.objects.select_related("filiere", "filiere__school"), pk=pk)
    if not check_school_permission(request.user, exam.filiere.school):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier cette épreuve.")

    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = ExamAdminForm(request.POST, request.FILES, instance=exam, active_filiere=exam.filiere)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.is_free = form.cleaned_data["is_free"]
            exam.is_published = form.cleaned_data["is_published"]
            exam.save()

            messages.success(request, f"Épreuve « {exam.title} » mise à jour avec succès.")
            return redirect("contributors:exam_list")
    else:
        form = ExamAdminForm(instance=exam, active_filiere=exam.filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "exam": exam,
        "is_create": False,
    }
    return render(request, "contributors/exams/form.html", context)


@contributor_required
def exam_toggle_status_view(request, pk):
    """Changer le statut de publication d'une épreuve (Brouillon <-> Publié)."""
    if request.method == "POST":
        exam = get_object_or_404(Exam.objects.select_related("filiere", "filiere__school"), pk=pk)
        if not check_school_permission(request.user, exam.filiere.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à modifier cette épreuve.")

        exam.is_published = not exam.is_published
        exam.save()

        new_status = "publiée" if exam.is_published else "mise en brouillon"
        messages.success(request, f"L'épreuve « {exam.title} » est maintenant {new_status}.")
    return redirect("contributors:exam_list")


@contributor_required
def exam_delete_view(request, pk):
    """Supprimer une épreuve d'examen."""
    if request.method == "POST":
        exam = get_object_or_404(Exam.objects.select_related("filiere", "filiere__school"), pk=pk)
        if not check_school_permission(request.user, exam.filiere.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à supprimer cette épreuve.")

        title = exam.title
        exam.delete()
        messages.success(request, f"Épreuve « {title} » supprimée avec succès.")
    return redirect("contributors:exam_list")


# ==========================================
# 2. RÉSUMÉS (SUMMARIES) MANAGEMENT
# ==========================================

@contributor_required
def summary_list_view(request):
    """Liste et recherche des résumés de cours."""
    active_school, active_filiere = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()

    qs = Summary.objects.select_related("subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school")
    if active_school:
        qs = qs.filter(subject__semester__filiere__school=active_school)
    if active_filiere:
        qs = qs.filter(subject__semester__filiere=active_filiere)

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(subject__name__icontains=q))

    summaries_list = qs.order_by("-created_at")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "summaries": summaries_list,
        "q": q,
    }
    return render(request, "contributors/summaries/list.html", context)


@contributor_required
def summary_create_view(request):
    """Créer un nouveau résumé de cours."""
    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = SummaryAdminForm(request.POST, request.FILES, active_filiere=active_filiere)
        if form.is_valid():
            sm = form.save(commit=False)
            sm.author = request.user
            sm.save()
            messages.success(request, f"Résumé « {sm.title} » créé avec succès.")
            return redirect("contributors:summary_list")
    else:
        form = SummaryAdminForm(active_filiere=active_filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "is_create": True,
    }
    return render(request, "contributors/summaries/form.html", context)


@contributor_required
def summary_edit_view(request, pk):
    """Modifier un résumé de cours existant."""
    sm = get_object_or_404(Summary.objects.select_related("subject__semester__filiere__school"), pk=pk)
    if not check_school_permission(request.user, sm.subject.semester.filiere.school):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier ce résumé.")

    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = SummaryAdminForm(request.POST, request.FILES, instance=sm, active_filiere=sm.subject.semester.filiere)
        if form.is_valid():
            form.save()
            messages.success(request, f"Résumé « {sm.title} » mis à jour avec succès.")
            return redirect("contributors:summary_list")
    else:
        form = SummaryAdminForm(instance=sm, active_filiere=sm.subject.semester.filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "summary_obj": sm,
        "is_create": False,
    }
    return render(request, "contributors/summaries/form.html", context)


@contributor_required
def summary_toggle_status_view(request, pk):
    """Basculer le statut de publication d'un résumé."""
    if request.method == "POST":
        sm = get_object_or_404(Summary.objects.select_related("subject__semester__filiere__school"), pk=pk)
        if not check_school_permission(request.user, sm.subject.semester.filiere.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à modifier ce résumé.")

        sm.publication_status = "DRAFT" if sm.publication_status == "PUBLISHED" else "PUBLISHED"
        sm.save()
        messages.success(request, f"Le statut du résumé « {sm.title} » a été mis à jour.")
    return redirect("contributors:summary_list")


@contributor_required
def summary_delete_view(request, pk):
    """Supprimer un résumé de cours."""
    if request.method == "POST":
        sm = get_object_or_404(Summary.objects.select_related("subject__semester__filiere__school"), pk=pk)
        if not check_school_permission(request.user, sm.subject.semester.filiere.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à supprimer ce résumé.")

        title = sm.title
        sm.delete()
        messages.success(request, f"Résumé « {title} » supprimé.")
    return redirect("contributors:summary_list")


# ==========================================
# 3. GUIDES METHODOLOGIQUES
# ==========================================

@contributor_required
def guide_list_view(request):
    """Liste et recherche des guides de matières."""
    active_school, active_filiere = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()

    qs = Guide.objects.select_related("subject", "subject__semester__filiere")
    if active_school:
        qs = qs.filter(subject__semester__filiere__school=active_school)
    if active_filiere:
        qs = qs.filter(subject__semester__filiere=active_filiere)

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(subject__name__icontains=q))

    guides_list = qs.order_by("-created_at")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "guides": guides_list,
        "q": q,
    }
    return render(request, "contributors/guides/list.html", context)


@contributor_required
def guide_create_view(request):
    """Créer un nouveau guide méthodologique."""
    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = GuideAdminForm(request.POST, request.FILES, active_filiere=active_filiere)
        if form.is_valid():
            gd = form.save(commit=False)
            gd.author = request.user
            gd.save()
            messages.success(request, f"Guide « {gd.title} » créé avec succès.")
            return redirect("contributors:guide_list")
    else:
        form = GuideAdminForm(active_filiere=active_filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "is_create": True,
    }
    return render(request, "contributors/guides/form.html", context)


@contributor_required
def guide_edit_view(request, pk):
    """Modifier un guide méthodologique existant."""
    gd = get_object_or_404(Guide.objects.select_related("subject__semester__filiere__school"), pk=pk)
    if not check_school_permission(request.user, gd.subject.semester.filiere.school):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier ce guide.")

    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = GuideAdminForm(request.POST, request.FILES, instance=gd, active_filiere=gd.subject.semester.filiere)
        if form.is_valid():
            form.save()
            messages.success(request, f"Guide « {gd.title} » mis à jour avec succès.")
            return redirect("contributors:guide_list")
    else:
        form = GuideAdminForm(instance=gd, active_filiere=gd.subject.semester.filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "guide_obj": gd,
        "is_create": False,
    }
    return render(request, "contributors/guides/form.html", context)


@contributor_required
def guide_toggle_status_view(request, pk):
    """Basculer le statut de publication d'un guide."""
    if request.method == "POST":
        gd = get_object_or_404(Guide.objects.select_related("subject__semester__filiere__school"), pk=pk)
        if not check_school_permission(request.user, gd.subject.semester.filiere.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à modifier ce guide.")

        gd.publication_status = "DRAFT" if gd.publication_status == "PUBLISHED" else "PUBLISHED"
        gd.save()
        messages.success(request, f"Statut du guide « {gd.title} » mis à jour.")
    return redirect("contributors:guide_list")


@contributor_required
def guide_delete_view(request, pk):
    """Supprimer un guide méthodologique."""
    if request.method == "POST":
        gd = get_object_or_404(Guide.objects.select_related("subject__semester__filiere__school"), pk=pk)
        if not check_school_permission(request.user, gd.subject.semester.filiere.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à supprimer ce guide.")

        title = gd.title
        gd.delete()
        messages.success(request, f"Guide « {title} » supprimé.")
    return redirect("contributors:guide_list")


# ==========================================
# 4. CONSEILS & ARTICLES
# ==========================================

@contributor_required
def article_list_view(request):
    """Liste et recherche des articles et conseils d'études."""
    active_school, active_filiere = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()

    qs = Article.objects.all()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(summary__icontains=q))

    articles = qs.order_by("-created_at")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "articles": articles,
        "q": q,
    }
    return render(request, "contributors/articles/list.html", context)


@contributor_required
def article_create_view(request):
    """Rédiger un nouveau conseil d'étude / article."""
    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = ArticleAdminForm(request.POST)
        if form.is_valid():
            art = form.save(commit=False)
            art.author = request.user
            if active_school:
                art.target_school = active_school
            if active_filiere:
                art.target_filiere = active_filiere
            art.save()
            messages.success(request, f"Article « {art.title} » rédigé avec succès.")
            return redirect("contributors:article_list")
    else:
        form = ArticleAdminForm()

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "is_create": True,
    }
    return render(request, "contributors/articles/form.html", context)


@contributor_required
def article_edit_view(request, pk):
    """Modifier un conseil d'étude existant."""
    art = get_object_or_404(Article, pk=pk)
    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = ArticleAdminForm(request.POST, instance=art)
        if form.is_valid():
            form.save()
            messages.success(request, f"Article « {art.title} » mis à jour avec succès.")
            return redirect("contributors:article_list")
    else:
        form = ArticleAdminForm(instance=art)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "article_obj": art,
        "is_create": False,
    }
    return render(request, "contributors/articles/form.html", context)


@contributor_required
def article_toggle_status_view(request, pk):
    """Changer le statut d'un conseil d'étude (Brouillon <-> Publié)."""
    if request.method == "POST":
        art = get_object_or_404(Article, pk=pk)
        art.publication_status = "DRAFT" if art.publication_status == "PUBLISHED" else "PUBLISHED"
        art.save()
        messages.success(request, f"Statut de l'article « {art.title} » mis à jour.")
    return redirect("contributors:article_list")


@contributor_required
def article_delete_view(request, pk):
    """Supprimer un conseil d'étude."""
    if request.method == "POST":
        art = get_object_or_404(Article, pk=pk)
        title = art.title
        art.delete()
        messages.success(request, f"Article « {title} » supprimé.")
    return redirect("contributors:article_list")


# ==========================================
# 5. MATIÈRES / UE & STRUCTURE ACADÉMIQUE
# ==========================================

@contributor_required
def subject_list_view(request):
    """Liste et gestion des Unités d'Enseignement (Matières)."""
    active_school, active_filiere = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()

    qs = Subject.objects.select_related("semester", "semester__filiere", "semester__filiere__school").annotate(
        exams_count=Count("exams")
    )
    if active_school:
        qs = qs.filter(semester__filiere__school=active_school)
    if active_filiere:
        qs = qs.filter(semester__filiere=active_filiere)

    if q:
        qs = qs.filter(name__icontains=q)

    subjects = qs.order_by("semester__filiere", "name")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "subjects": subjects,
        "q": q,
    }
    return render(request, "contributors/subjects/list.html", context)


@contributor_required
def subject_create_view(request):
    """Créer une nouvelle matière / UE."""
    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = SubjectAdminForm(request.POST, active_filiere=active_filiere)
        if form.is_valid():
            sb = form.save()
            messages.success(request, f"Matière « {sb.name} » créée avec succès.")
            return redirect("contributors:subject_list")
    else:
        form = SubjectAdminForm(active_filiere=active_filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "is_create": True,
    }
    return render(request, "contributors/subjects/form.html", context)


@contributor_required
def subject_edit_view(request, pk):
    """Modifier une matière / UE existante."""
    sb = get_object_or_404(Subject.objects.select_related("semester__filiere__school"), pk=pk)
    if not check_school_permission(request.user, sb.semester.filiere.school):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier cette matière.")

    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = SubjectAdminForm(request.POST, instance=sb, active_filiere=sb.semester.filiere)
        if form.is_valid():
            form.save()
            messages.success(request, f"Matière « {sb.name} » mise à jour.")
            return redirect("contributors:subject_list")
    else:
        form = SubjectAdminForm(instance=sb, active_filiere=sb.semester.filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
        "subject_obj": sb,
        "is_create": False,
    }
    return render(request, "contributors/subjects/form.html", context)


@contributor_required
def structure_overview_view(request):
    """Vue d'ensemble hiérarchique de la structure académique."""
    active_school, active_filiere = get_active_academic_context(request)

    schools = School.objects.filter(is_active=True).prefetch_related("filieres", "filieres__semesters", "filieres__semesters__subjects")
    if active_school:
        schools = schools.filter(pk=active_school.pk)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "schools": schools,
    }
    return render(request, "contributors/structure/overview.html", context)


# ==========================================
# 6. ÉTUDIANTS, PAIEMENTS & NOTIFICATIONS
# ==========================================

@contributor_required
def student_list_view(request):
    """Annuaire privé des étudiants inscrits."""
    active_school, active_filiere = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()

    qs = StudentProfile.objects.select_related("user", "school", "level", "filiere")
    if active_school:
        qs = qs.filter(school=active_school)
    if active_filiere:
        qs = qs.filter(filiere=active_filiere)

    if q:
        qs = qs.filter(Q(user__username__icontains=q) | Q(user__email__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))

    students = qs.order_by("-user__date_joined")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "students": students,
        "q": q,
    }
    return render(request, "contributors/students/list.html", context)


@contributor_required
def payment_list_view(request):
    """Aperçu des accès Pass Semestre et transactions."""
    active_school, active_filiere = get_active_academic_context(request)

    access_records = SemesterAccess.objects.select_related("user", "filiere", "semester").order_by("-activated_at")
    if active_filiere:
        access_records = access_records.filter(filiere=active_filiere)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "access_records": access_records,
    }
    return render(request, "contributors/payments/list.html", context)


@contributor_required
def notification_create_view(request):
    """Créer et diffuser une notification ciblée aux étudiants."""
    active_school, active_filiere = get_active_academic_context(request)

    if request.method == "POST":
        form = NotificationAdminForm(request.POST)
        if form.is_valid():
            title = form.cleaned_data["title"]
            message_text = form.cleaned_data["message"]
            scope = form.cleaned_data["scope"]

            school_arg = active_school if scope == "SCHOOL" else None
            filiere_arg = active_filiere if scope == "FILIERE" else None

            sent_count = notify_target_students(
                school=school_arg,
                filiere=filiere_arg,
                notification_type="SYSTEM",
                title=title,
                message=message_text,
                link=""
            )

            messages.success(request, f"Notification « {title} » envoyée à {sent_count} étudiant(s).")
            return redirect("contributors:admin_dashboard")
    else:
        form = NotificationAdminForm()

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "form": form,
    }
    return render(request, "contributors/notifications/form.html", context)
