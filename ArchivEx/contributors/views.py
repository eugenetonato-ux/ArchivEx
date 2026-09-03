import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.http import JsonResponse, HttpResponseForbidden, FileResponse, Http404

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from academics.parser import parse_exam_filename
from exams.models import Exam
from content.models import Summary, Guide, Article, CloudFile
from accounts.models import StudentProfile
from payments.models import SemesterAccess, Payment
from notifications.services import notify_target_students

from .decorators import contributor_required, get_active_academic_context, is_user_contributor
from .permissions import check_school_permission
from .forms import (
    ContextSelectForm,
    ExamAdminForm,
    CloudFileAdminForm,
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

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
    available_semesters = Semester.objects.filter(filiere=active_filiere) if active_filiere else Semester.objects.none()

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "available_schools": available_schools,
        "available_filieres": available_filieres,
        "available_semesters": available_semesters,
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
    """Change le contexte académique actif (Université + Filière + Semestre) dans la session."""
    school_id = request.GET.get("school_id") or request.POST.get("school_id")
    filiere_id = request.GET.get("filiere_id") or request.POST.get("filiere_id")
    semester_id = request.GET.get("semester_id") or request.POST.get("semester_id")

    if school_id:
        if school_id == "all":
            request.session["admin_active_school_id"] = None
            request.session["admin_active_filiere_id"] = None
            request.session["admin_active_semester_id"] = None
            messages.info(request, "Contexte réinitialisé : Toutes les universités")
        else:
            school = get_object_or_404(School, pk=school_id)
            if not check_school_permission(request.user, school):
                raise PermissionDenied("Vous n'êtes pas autorisé à gérer le contenu de cette université.")
            
            old_school_id = request.session.get("admin_active_school_id")
            request.session["admin_active_school_id"] = school.id

            if filiere_id:
                if filiere_id == "all":
                    request.session["admin_active_filiere_id"] = None
                    request.session["admin_active_semester_id"] = None
                else:
                    filiere = Filiere.objects.filter(pk=filiere_id, school=school).first()
                    request.session["admin_active_filiere_id"] = filiere.id if filiere else None
                    if semester_id and semester_id != "all":
                        sem = Semester.objects.filter(pk=semester_id, filiere=filiere).first()
                        request.session["admin_active_semester_id"] = sem.id if sem else None
                    else:
                        first_sem = Semester.objects.filter(filiere=filiere).first() if filiere else None
                        request.session["admin_active_semester_id"] = first_sem.id if first_sem else None
            elif old_school_id != school.id:
                first_filiere = Filiere.objects.filter(school=school).first()
                request.session["admin_active_filiere_id"] = first_filiere.id if first_filiere else None
                first_sem = Semester.objects.filter(filiere=first_filiere).first() if first_filiere else None
                request.session["admin_active_semester_id"] = first_sem.id if first_sem else None

            filiere_name = ""
            if request.session.get("admin_active_filiere_id"):
                f = Filiere.objects.filter(pk=request.session.get("admin_active_filiere_id")).first()
                if f:
                    filiere_name = f" — {f.name}"

            messages.success(request, f"Contexte actif : {school.name}{filiere_name}")

    elif filiere_id:
        if filiere_id == "all":
            request.session["admin_active_filiere_id"] = None
            request.session["admin_active_semester_id"] = None
            messages.info(request, "Filière réinitialisée : Toutes les filières")
        else:
            filiere = Filiere.objects.filter(pk=filiere_id).first()
            if filiere:
                request.session["admin_active_school_id"] = filiere.school_id
                request.session["admin_active_filiere_id"] = filiere.id
                if semester_id and semester_id != "all":
                    sem = Semester.objects.filter(pk=semester_id, filiere=filiere).first()
                    request.session["admin_active_semester_id"] = sem.id if sem else None
                else:
                    first_sem = Semester.objects.filter(filiere=filiere).first()
                    request.session["admin_active_semester_id"] = first_sem.id if first_sem else None
                messages.success(request, f"Filière active : {filiere.name} ({filiere.school.name})")

    elif semester_id:
        if semester_id == "all":
            request.session["admin_active_semester_id"] = None
            messages.info(request, "Semestre réinitialisé")
        else:
            sem = Semester.objects.filter(pk=semester_id).first()
            if sem:
                request.session["admin_active_school_id"] = sem.filiere.school_id
                request.session["admin_active_filiere_id"] = sem.filiere_id
                request.session["admin_active_semester_id"] = sem.id
                messages.success(request, f"Semestre actif : {sem.label} ({sem.filiere.name})")

    next_url = request.META.get("HTTP_REFERER") or "/administration/"
    return redirect(next_url)


# ==========================================
# 1. ÉPREUVES (EXAMS) MANAGEMENT
# ==========================================

@contributor_required
def exam_list_view(request):
    """Liste et recherche des épreuves dans le contexte actif."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
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
        "active_semester": active_semester,
        "exams": exams,
        "q": q,
    }
    return render(request, "contributors/exams/list.html", context)


def _process_exam_cloud_files(form, exam, target_semester, active_school, active_filiere, active_semester, user):
    cloud_file = form.cleaned_data.get("cloud_file")
    cloud_corr = form.cleaned_data.get("cloud_correction_file")
    cloud_sum = form.cleaned_data.get("cloud_summary_file")

    school_obj = target_semester.filiere.school if target_semester and getattr(target_semester, "filiere", None) else active_school
    filiere_obj = target_semester.filiere if target_semester and getattr(target_semester, "filiere", None) else active_filiere
    semester_obj = target_semester or active_semester

    if cloud_file:
        exam.cloud_file = cloud_file
        if cloud_file.file:
            exam.file = cloud_file.file
    elif form.cleaned_data.get("file"):
        cf = CloudFile.objects.create(
            title=f"Épreuve — {exam.title}",
            file=form.cleaned_data["file"],
            file_type="EXAM",
            school=school_obj,
            filiere=filiere_obj,
            semester=semester_obj,
            uploaded_by=user,
        )
        exam.cloud_file = cf

    if cloud_corr:
        exam.cloud_correction_file = cloud_corr
        if cloud_corr.file:
            exam.correction_file = cloud_corr.file
    elif form.cleaned_data.get("correction_file"):
        cf = CloudFile.objects.create(
            title=f"Correction — {exam.title}",
            file=form.cleaned_data["correction_file"],
            file_type="CORRECTION",
            school=school_obj,
            filiere=filiere_obj,
            semester=semester_obj,
            uploaded_by=user,
        )
        exam.cloud_correction_file = cf

    if cloud_sum:
        exam.cloud_summary_file = cloud_sum
        if cloud_sum.file:
            exam.summary_file = cloud_sum.file
    elif form.cleaned_data.get("summary_file"):
        cf = CloudFile.objects.create(
            title=f"Résumé — {exam.title}",
            file=form.cleaned_data["summary_file"],
            file_type="SUMMARY",
            school=school_obj,
            filiere=filiere_obj,
            semester=semester_obj,
            uploaded_by=user,
        )
        exam.cloud_summary_file = cf


@contributor_required
def exam_create_view(request):
    """Ajouter une épreuve d'examen avec héritage du contexte actif et saisie libre de la matière."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
    if active_school and not check_school_permission(request.user, active_school):
        raise PermissionDenied("Vous n'êtes pas autorisé à ajouter une épreuve pour cette université.")

    if request.method == "POST":
        form = ExamAdminForm(request.POST, request.FILES, active_filiere=active_filiere, active_semester=active_semester)
        if form.is_valid():
            exam = form.save(commit=False)

            # Déterminer le semestre hérité ou sélectionné
            target_semester = form.cleaned_data.get("semester") or active_semester
            if not target_semester and active_filiere:
                target_semester = Semester.objects.filter(filiere=active_filiere).first()
            if not target_semester and active_filiere:
                target_semester = Semester.objects.create(filiere=active_filiere, label="Semestre 1", number=1)

            exam.semester = target_semester
            exam.filiere = target_semester.filiere
            exam.level = target_semester.filiere.level

            # Traitement de la matière (saisie libre)
            subject_name = form.cleaned_data["subject_name"].strip()
            subject = Subject.objects.filter(semester=target_semester, name__iexact=subject_name).first()
            if not subject:
                subject = Subject.objects.create(
                    semester=target_semester,
                    name=subject_name,
                    is_active=True
                )
            exam.subject = subject

            raw_year_input = str(request.POST.get("year", "")).strip()
            if raw_year_input:
                if "-" in raw_year_input:
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=raw_year_input)
                elif raw_year_input.isdigit():
                    yr_i = int(raw_year_input)
                    lbl = f"{yr_i-1}-{yr_i}"
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=lbl)
                else:
                    ay_obj = None
                if ay_obj:
                    exam.academic_year = ay_obj
            elif not getattr(exam, "academic_year_id", None):
                if target_semester and getattr(target_semester, "academic_year", None):
                    exam.academic_year = target_semester.academic_year
                else:
                    exam.academic_year = AcademicYear.objects.first()

            exam.is_free = form.cleaned_data["is_free"]
            exam.is_published = form.cleaned_data["is_published"]

            # Traitement des fichiers Cloud et téléversements directs
            _process_exam_cloud_files(form, exam, target_semester, active_school, active_filiere, active_semester, request.user)

            exam.save()

            status_str = "publiée" if exam.is_published else "enregistrée en brouillon"
            messages.success(request, f"Épreuve « {exam.title} » publiée avec succès sur le site public pour {exam.subject.name}.")
            return redirect("contributors:exam_list")
    else:
        form = ExamAdminForm(active_filiere=active_filiere, active_semester=active_semester)

    available_subjects = Subject.objects.filter(semester__filiere=active_filiere).select_related("semester") if active_filiere else Subject.objects.none()

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "available_subjects": available_subjects,
        "form": form,
        "is_create": True,
    }
    return render(request, "contributors/exams/form.html", context)


@contributor_required
def exam_edit_view(request, pk):
    """Modifier une épreuve existante."""
    exam = get_object_or_404(Exam.objects.select_related("filiere", "filiere__school", "subject", "semester"), pk=pk)
    if not check_school_permission(request.user, exam.filiere.school):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier cette épreuve.")

    active_school, active_filiere, active_semester = get_active_academic_context(request)

    if request.method == "POST":
        form = ExamAdminForm(request.POST, request.FILES, instance=exam, active_filiere=exam.filiere, active_semester=exam.semester)
        if form.is_valid():
            exam = form.save(commit=False)

            target_semester = form.cleaned_data.get("semester") or exam.semester or active_semester
            exam.semester = target_semester
            exam.filiere = target_semester.filiere
            exam.level = target_semester.filiere.level

            subject_name = form.cleaned_data["subject_name"].strip()
            subject = Subject.objects.filter(semester=target_semester, name__iexact=subject_name).first()
            if not subject:
                subject = Subject.objects.create(
                    semester=target_semester,
                    name=subject_name,
                    is_active=True
                )
            exam.subject = subject

            raw_year_input = str(request.POST.get("year", "")).strip()
            if raw_year_input:
                if "-" in raw_year_input:
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=raw_year_input)
                elif raw_year_input.isdigit():
                    yr_i = int(raw_year_input)
                    lbl = f"{yr_i-1}-{yr_i}"
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=lbl)
                else:
                    ay_obj = None
                if ay_obj:
                    exam.academic_year = ay_obj

            exam.is_free = form.cleaned_data["is_free"]
            exam.is_published = form.cleaned_data["is_published"]

            _process_exam_cloud_files(form, exam, target_semester, active_school, active_filiere, active_semester, request.user)

            exam.save()

            messages.success(request, f"Épreuve « {exam.title} » mise à jour avec succès.")
            return redirect("contributors:exam_list")
    else:
        form = ExamAdminForm(instance=exam, active_filiere=exam.filiere, active_semester=exam.semester)

    available_subjects = Subject.objects.filter(semester__filiere=exam.filiere).select_related("semester")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "available_subjects": available_subjects,
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

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

    active_school, active_filiere, active_semester = get_active_academic_context(request)

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
    active_school, active_filiere, active_semester = get_active_academic_context(request)
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

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

    active_school, active_filiere, active_semester = get_active_academic_context(request)

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
    active_school, active_filiere, active_semester = get_active_academic_context(request)
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

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
    active_school, active_filiere, active_semester = get_active_academic_context(request)
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

    if request.method == "POST":
        form = SubjectAdminForm(request.POST, request.FILES, active_filiere=active_filiere)
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

    active_school, active_filiere, active_semester = get_active_academic_context(request)

    if request.method == "POST":
        form = SubjectAdminForm(request.POST, request.FILES, instance=sb, active_filiere=sb.semester.filiere)
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
    active_school, active_filiere, active_semester = get_active_academic_context(request)

    schools = School.objects.filter(is_active=True).prefetch_related("filieres", "filieres__semesters", "filieres__semesters__subjects")
    if active_school:
        schools = schools.filter(pk=active_school.pk)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "schools": schools,
    }
    return render(request, "contributors/structure/overview.html", context)


@contributor_required
def resource_completeness_view(request):
    """
    Vue de synthèse de la complétude des ressources pour les contributeurs.
    Permet d'identifier rapidement les épreuves sans correction ou sans résumé.
    """
    active_school, active_filiere, active_semester = get_active_academic_context(request)

    exams = Exam.objects.select_related("subject", "semester", "filiere", "filiere__school", "summary").order_by("-created_at")

    if active_school:
        exams = exams.filter(filiere__school=active_school)
    if active_filiere:
        exams = exams.filter(filiere=active_filiere)
    if active_semester:
        exams = exams.filter(semester=active_semester)

    total_exams = exams.count()
    with_correction_count = exams.filter(correction_file__isnull=False).exclude(correction_file="").count()

    with_summary_count = exams.filter(
        Q(summary_file__isnull=False) & ~Q(summary_file="") | Q(summary__isnull=False)
    ).count()

    complete_count = 0
    all_exams_list = list(exams)
    for e in all_exams_list:
        if e.has_correction and e.has_summary:
            complete_count += 1

    without_correction_count = total_exams - with_correction_count
    without_summary_count = total_exams - with_summary_count

    filter_type = request.GET.get("filter", "all")
    if filter_type == "missing_correction":
        exams_list = [e for e in all_exams_list if not e.has_correction]
    elif filter_type == "missing_summary":
        exams_list = [e for e in all_exams_list if not e.has_summary]
    elif filter_type == "missing_both":
        exams_list = [e for e in all_exams_list if not e.has_correction and not e.has_summary]
    elif filter_type == "complete":
        exams_list = [e for e in all_exams_list if e.has_correction and e.has_summary]
    else:
        exams_list = all_exams_list[:100]

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "total_exams": total_exams,
        "with_correction_count": with_correction_count,
        "without_correction_count": without_correction_count,
        "with_summary_count": with_summary_count,
        "without_summary_count": without_summary_count,
        "complete_count": complete_count,
        "selected_filter": filter_type,
        "exams": exams_list,
    }
    return render(request, "contributors/completeness.html", context)


# ==========================================
# 6. ÉTUDIANTS, PAIEMENTS & NOTIFICATIONS
# ==========================================

@contributor_required
def student_list_view(request):
    """Annuaire privé des étudiants inscrits."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
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
    """Supervision des paiements SebPay Mobile Money et accès Pass Semestre."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("filter", "all")

    payments_qs = Payment.objects.select_related("user", "semester", "semester__filiere").order_by("-created_at")

    if active_school:
        payments_qs = payments_qs.filter(semester__filiere__school=active_school)
    if active_filiere:
        payments_qs = payments_qs.filter(semester__filiere=active_filiere)
    if active_semester:
        payments_qs = payments_qs.filter(semester=active_semester)

    if q:
        payments_qs = payments_qs.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(external_reference__icontains=q) |
            Q(sebpay_transaction_id__icontains=q) |
            Q(phone_number__icontains=q)
        )

    all_payments = list(payments_qs)
    total_count = len(all_payments)
    pending_count = sum(1 for p in all_payments if p.is_pending)
    approved_count = sum(1 for p in all_payments if p.is_approved)
    rejected_count = sum(1 for p in all_payments if p.is_rejected)
    total_revenue = sum(p.amount for p in all_payments if p.is_approved)

    if status_filter == "pending":
        filtered_payments = [p for p in all_payments if p.is_pending]
    elif status_filter == "approved":
        filtered_payments = [p for p in all_payments if p.is_approved]
    elif status_filter == "rejected":
        filtered_payments = [p for p in all_payments if p.is_rejected]
    else:
        filtered_payments = all_payments

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "payments": filtered_payments,
        "q": q,
        "status_filter": status_filter,
        "total_count": total_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "total_revenue": total_revenue,
    }
    return render(request, "contributors/payments/list.html", context)


@contributor_required
def notification_create_view(request):
    """Créer et diffuser une notification ciblée aux étudiants."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)

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


# ==========================================
# 7. BIBLIOTHÈQUE CLOUD INTEGRATED & DÉPÔT CENTRAL
# ==========================================

@contributor_required
def library_index_view(request):
    """Bibliothèque Cloud Integrated : Dépôt central de stockage des fichiers classé par UE."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
    q = request.GET.get("q", "").strip()
    type_filter = request.GET.get("filter", "all")

    qs = CloudFile.objects.select_related("school", "filiere", "semester", "uploaded_by").order_by("-created_at")

    if active_school:
        qs = qs.filter(Q(school=active_school) | Q(school__isnull=True))
    if active_filiere:
        qs = qs.filter(Q(filiere=active_filiere) | Q(filiere__isnull=True))
    if active_semester:
        qs = qs.filter(Q(semester=active_semester) | Q(semester__isnull=True))

    if q:
        qs = qs.filter(Q(title__icontains=q))

    if type_filter in ["EXAM", "CORRECTION", "SUMMARY", "OTHER"]:
        qs = qs.filter(file_type=type_filter)

    cloud_files = list(qs)
    total_count = len(cloud_files)
    exam_count = sum(1 for f in cloud_files if f.file_type == "EXAM")
    correction_count = sum(1 for f in cloud_files if f.file_type == "CORRECTION")
    summary_count = sum(1 for f in cloud_files if f.file_type == "SUMMARY")

    available_subjects = Subject.objects.filter(semester__filiere=active_filiere) if active_filiere else Subject.objects.all()

    grouped_cloud_files = {}
    for cf in cloud_files:
        parsed = parse_exam_filename(cf.title, available_subjects=available_subjects)
        cf.parsed_info = parsed
        matched_subj = parsed["matched_subject"]
        ue_name = matched_subj.name if matched_subj else (parsed["subject_candidate"] or "Noms non conformes / Non classés")
        
        if ue_name not in grouped_cloud_files:
            if not matched_subj and ue_name != "Noms non conformes / Non classés":
                matched_subj = Subject.objects.filter(name__iexact=ue_name.strip()).first()
            grouped_cloud_files[ue_name] = {
                "files": [],
                "matched_subject": matched_subj,
                "is_free": matched_subj.is_free if matched_subj else False,
                "is_free_correction": matched_subj.is_free_correction if matched_subj else False,
            }
        grouped_cloud_files[ue_name]["files"].append(cf)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "cloud_files": cloud_files,
        "grouped_cloud_files": grouped_cloud_files,
        "q": q,
        "type_filter": type_filter,
        "total_count": total_count,
        "exam_count": exam_count,
        "correction_count": correction_count,
        "summary_count": summary_count,
    }
    return render(request, "contributors/library/index.html", context)


@contributor_required
def cloud_file_create_view(request):
    """Déposer un fichier PDF sur la Bibliothèque Cloud Integrated (Stockage uniquement, sans publication)."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
    if active_school and not check_school_permission(request.user, active_school):
        raise PermissionDenied("Vous n'êtes pas autorisé à déposer des fichiers pour cette université.")

    if request.method == "POST":
        form = CloudFileAdminForm(request.POST, request.FILES)
        if form.is_valid():
            cloud_file = form.save(commit=False)
            if not cloud_file.school:
                cloud_file.school = active_school
            if not cloud_file.filiere:
                cloud_file.filiere = active_filiere
            if not cloud_file.semester:
                cloud_file.semester = active_semester
            cloud_file.uploaded_by = request.user
            cloud_file.save()

            messages.success(request, f"Fichier « {cloud_file.title} » conservé avec succès sur le Cloud Integrated (Non publié sur le site).")
            return redirect("contributors:library_index")
    else:
        form = CloudFileAdminForm(initial={
            "school": active_school,
            "filiere": active_filiere,
            "semester": active_semester,
        })

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "form": form,
    }
    return render(request, "contributors/library/form.html", context)


@contributor_required
def cloud_file_delete_view(request, pk):
    """Supprimer un fichier du stockage Cloud Integrated."""
    if request.method == "POST":
        cloud_file = get_object_or_404(CloudFile, pk=pk)
        if cloud_file.school and not check_school_permission(request.user, cloud_file.school):
            raise PermissionDenied("Vous n'êtes pas autorisé à supprimer ce fichier.")

        title = cloud_file.title
        cloud_file.delete()
        messages.success(request, f"Fichier Cloud « {title} » supprimé avec succès.")
    return redirect("contributors:library_index")


@contributor_required
def cloud_file_edit_view(request, pk):
    """Permet de modifier ou renommer un fichier dans le Cloud Storage (Titre, Type, Filière, Semestre)."""
    cloud_file = get_object_or_404(CloudFile, pk=pk)
    active_school, active_filiere, active_semester = get_active_academic_context(request)

    if cloud_file.school and not check_school_permission(request.user, cloud_file.school):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier ce fichier.")

    if request.method == "POST":
        form = CloudFileAdminForm(request.POST, request.FILES, instance=cloud_file, active_filiere=active_filiere, active_semester=active_semester)
        if form.is_valid():
            cf = form.save(commit=False)
            if not cf.school and active_school:
                cf.school = active_school
            cf.save()
            messages.success(request, f"Fichier Cloud « {cf.title} » mis à jour et renommé avec succès.")
            return redirect("contributors:library_index")
    else:
        form = CloudFileAdminForm(instance=cloud_file, active_filiere=active_filiere, active_semester=active_semester)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "form": form,
        "cloud_file": cloud_file,
        "is_edit": True,
    }
    return render(request, "contributors/library/form.html", context)


@contributor_required
def publish_from_cloud_view(request, pk):
    """Pré-remplit le formulaire de publication d'épreuve avec un fichier Cloud sélectionné et recherche auto du corrigé/résumé."""
    cloud_file = get_object_or_404(CloudFile, pk=pk)
    active_school, active_filiere, active_semester = get_active_academic_context(request)

    target_filiere = cloud_file.filiere or active_filiere
    available_subjects = Subject.objects.filter(semester__filiere=target_filiere) if target_filiere else Subject.objects.all()

    parsed = parse_exam_filename(cloud_file.title, available_subjects=available_subjects)

    detected_subject_name = parsed["matched_subject"].name if parsed["matched_subject"] else (parsed["subject_candidate"] or "")
    detected_academic_year = parsed["detected_academic_year"] or ""
    initial_title = parsed["clean_title"] or cloud_file.title.replace("Épreuve — ", "").replace(".pdf", "").strip()

    # Recherche automatique du corrigé et du résumé associés dans le Cloud Storage
    auto_corr_cloud = None
    auto_sum_cloud = None

    if detected_subject_name:
        corr_qs = CloudFile.objects.filter(file_type="CORRECTION").filter(
            Q(title__icontains=detected_subject_name) | Q(title__icontains=cloud_file.title)
        )
        if target_filiere:
            corr_qs = corr_qs.filter(Q(filiere=target_filiere) | Q(filiere__isnull=True))
        auto_corr_cloud = corr_qs.first()

        sum_qs = CloudFile.objects.filter(file_type="SUMMARY").filter(
            Q(title__icontains=detected_subject_name) | Q(title__icontains=cloud_file.title)
        )
        if target_filiere:
            sum_qs = sum_qs.filter(Q(filiere=target_filiere) | Q(filiere__isnull=True))
        auto_sum_cloud = sum_qs.first()

    if request.method == "POST":
        form = ExamAdminForm(request.POST, request.FILES, active_filiere=target_filiere, active_semester=cloud_file.semester or active_semester)
        if form.is_valid():
            exam = form.save(commit=False)

            target_semester = form.cleaned_data.get("semester") or cloud_file.semester or active_semester
            if not target_semester and target_filiere:
                target_semester = Semester.objects.filter(filiere=target_filiere).first()
            if not target_semester and target_filiere:
                target_semester = Semester.objects.create(filiere=target_filiere, label="Semestre 1", number=1)

            exam.semester = target_semester
            exam.filiere = target_semester.filiere
            exam.level = target_semester.filiere.level

            subject_name = form.cleaned_data["subject_name"].strip()
            subject = Subject.objects.filter(semester=target_semester, name__iexact=subject_name).first()
            if not subject:
                subject = Subject.objects.create(
                    semester=target_semester,
                    name=subject_name,
                    is_active=True
                )
            exam.subject = subject

            raw_year_input = str(request.POST.get("year", "")).strip()
            if raw_year_input:
                if "-" in raw_year_input:
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=raw_year_input)
                elif raw_year_input.isdigit():
                    yr_i = int(raw_year_input)
                    lbl = f"{yr_i-1}-{yr_i}"
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=lbl)
                else:
                    ay_obj = None
                if ay_obj:
                    exam.academic_year = ay_obj
            elif not getattr(exam, "academic_year_id", None):
                exam.academic_year = AcademicYear.objects.first()

            exam.is_free = form.cleaned_data["is_free"]
            exam.is_published = form.cleaned_data["is_published"]

            _process_exam_cloud_files(form, exam, target_semester, active_school, target_filiere, active_semester, request.user)

            exam.save()

            messages.success(request, f"Épreuve « {exam.title} » publiée avec succès sur le site public pour {exam.subject.name}.")
            return redirect("contributors:exam_list")
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire pour valider la publication.")
    else:
        form_initial = {
            "title": initial_title,
            "subject_name": detected_subject_name,
            "year": detected_academic_year or "2025-2026",
            "exam_type": "examen",
            "is_published": "True",
            "is_free": "False",
            "cloud_file": cloud_file if cloud_file.file_type == "EXAM" else None,
            "cloud_correction_file": cloud_file if cloud_file.file_type == "CORRECTION" else auto_corr_cloud,
            "cloud_summary_file": cloud_file if cloud_file.file_type == "SUMMARY" else auto_sum_cloud,
            "semester": cloud_file.semester or active_semester,
        }
        form = ExamAdminForm(initial=form_initial, active_filiere=target_filiere, active_semester=cloud_file.semester or active_semester)

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "available_subjects": available_subjects,
        "form": form,
        "is_create": True,
        "selected_cloud_file": cloud_file,
        "auto_corr_cloud": auto_corr_cloud,
        "auto_sum_cloud": auto_sum_cloud,
        "parsed_info": parsed,
    }
    return render(request, "contributors/exams/form.html", context)


@contributor_required
def publish_cloud_folder_view(request):
    """
    Publie directement sur le site public TOUTES les épreuves et corrigés d'un dossier / d'une UE depuis la bibliothèque Cloud.
    """
    active_school, active_filiere, active_semester = get_active_academic_context(request)
    subject_id = request.POST.get("subject_id") or request.GET.get("subject_id")
    ue_name = request.POST.get("ue_name") or request.GET.get("ue_name") or ""

    if ue_name == "Noms non conformes / Non classés":
        messages.warning(request, "Impossible de publier l'UE globale pour les fichiers non classés. Veuillez d'abord les renommer ou les publier individuellement.")
        return redirect("contributors:library_index")

    subject = None
    if subject_id:
        subject = Subject.objects.filter(pk=subject_id).first()

    if not subject and ue_name:
        target_semester = active_semester
        if not target_semester and active_filiere:
            target_semester = Semester.objects.filter(filiere=active_filiere).first()
        if not target_semester and active_school:
            target_filiere_obj = Filiere.objects.filter(school=active_school).first()
            if target_filiere_obj:
                target_semester = Semester.objects.filter(filiere=target_filiere_obj).first()

        if not target_semester:
            target_semester = Semester.objects.first()

        subject, _ = Subject.objects.get_or_create(
            name=ue_name.strip(),
            semester=target_semester,
            defaults={"is_active": True}
        )

    if not subject:
        messages.error(request, "Impossible d'identifier ou de créer l'UE à publier.")
        return redirect("contributors:library_index")

    target_semester = subject.semester
    target_filiere = target_semester.filiere

    # Récupérer les fichiers Cloud du contexte académique
    all_cloud = CloudFile.objects.select_related("school", "filiere", "semester").order_by("-created_at")
    if active_school:
        all_cloud = all_cloud.filter(Q(school=active_school) | Q(school__isnull=True))
    if active_filiere:
        all_cloud = all_cloud.filter(Q(filiere=active_filiere) | Q(filiere__isnull=True))
    if active_semester:
        all_cloud = all_cloud.filter(Q(semester=active_semester) | Q(semester__isnull=True))

    available_subjects = Subject.objects.filter(semester__filiere=target_filiere) if target_filiere else Subject.objects.all()

    # Isoler UNIQUEMENT les épreuves et corrigés appartenant réellement à cette UE
    matching_cloud_exams = []
    matching_cloud_corrections = []

    for cf in all_cloud:
        parsed = parse_exam_filename(cf.title, available_subjects=available_subjects)
        cf_ue = parsed["matched_subject"].name if parsed["matched_subject"] else (parsed["subject_candidate"] or "")
        
        # Correspondance exacte avec le nom de l'UE
        is_same_ue = (
            (parsed["matched_subject"] and parsed["matched_subject"].id == subject.id) or
            (cf_ue.strip().lower() == subject.name.strip().lower()) or
            (cf_ue.strip().lower() == ue_name.strip().lower()) or
            (subject.name.strip().lower() in cf.title.strip().lower())
        )
        if is_same_ue:
            if cf.file_type == "EXAM":
                matching_cloud_exams.append((cf, parsed))
            elif cf.file_type == "CORRECTION":
                matching_cloud_corrections.append((cf, parsed))

    published_count = 0
    with_corr_count = 0

    for cf, parsed in matching_cloud_exams:
        if cf.file:
            existing_exam = Exam.objects.filter(Q(cloud_file=cf) | Q(file=cf.file)).first()
        else:
            existing_exam = Exam.objects.filter(cloud_file=cf).first()

        if existing_exam:
            existing_exam.is_published = True
            existing_exam.save()
            published_count += 1
            continue

        yr_label = parsed["detected_academic_year"] or "2025-2026"
        if "-" in yr_label:
            ay_obj, _ = AcademicYear.objects.get_or_create(label=yr_label)
            yr_int = int(yr_label.split("-")[1])
        else:
            yr_int = 2025
            ay_obj = target_semester.academic_year or AcademicYear.objects.first()

        # Recherche du corrigé correspondant parmi les fichiers de cette même UE
        corr_cf = None
        for c_cf, c_parsed in matching_cloud_corrections:
            if c_parsed["clean_title"] == parsed["clean_title"] or cf.title in c_cf.title or subject.name in c_cf.title:
                corr_cf = c_cf
                break

        exam_title = cf.title.replace("Épreuve — ", "").replace(".pdf", "").strip()
        exam = Exam.objects.create(
            title=exam_title,
            subject=subject,
            semester=target_semester,
            filiere=target_filiere,
            level=target_filiere.level,
            academic_year=ay_obj,
            year=yr_int,
            exam_type="examen",
            cloud_file=cf,
            file=cf.file if cf.file else None,
            cloud_correction_file=corr_cf,
            correction_file=corr_cf.file if (corr_cf and corr_cf.file) else None,
            is_free=subject.is_free,
            is_free_correction=subject.is_free_correction,
            is_published=True,
        )
        published_count += 1
        if corr_cf:
            with_corr_count += 1

    messages.success(
        request,
        f"{published_count} épreuve(s) pour l'UE « {subject.name} » ont été publiées sur le site public ({with_corr_count} avec corrigé rattaché)."
    )
    return redirect("contributors:library_index")


@contributor_required
def toggle_ue_premium_view(request):
    """
    Bascule l'état Premium / Gratuit d'une UE dans le Cloud Storage (Bouton Épreuves ou Bouton Corrigés & Résumés).
    """
    if request.method == "POST":
        subject_id = request.POST.get("subject_id")
        ue_name = request.POST.get("ue_name", "").strip()
        target_type = request.POST.get("target_type", "exam")

        active_school, active_filiere, active_semester = get_active_academic_context(request)
        subject = None
        if subject_id:
            subject = Subject.objects.filter(pk=subject_id).first()

        if not subject and ue_name:
            target_semester = active_semester
            if not target_semester and active_filiere:
                target_semester = Semester.objects.filter(filiere=active_filiere).first()
            if not target_semester:
                target_semester = Semester.objects.first()

            subject, _ = Subject.objects.get_or_create(
                name=ue_name,
                semester=target_semester,
                defaults={"is_active": True}
            )

        if subject:
            if target_type == "exam":
                subject.is_free = not subject.is_free
                subject.save()
                Exam.objects.filter(subject=subject).update(is_free=subject.is_free)
                status_txt = "Gratuit (Accès libre)" if subject.is_free else "Premium (Pass Semestre requis)"
                messages.success(request, f"Épreuves de l'UE « {subject.name} » basculées en mode : {status_txt}")

            elif target_type == "correction":
                subject.is_free_correction = not subject.is_free_correction
                subject.save()
                Exam.objects.filter(subject=subject).update(is_free_correction=subject.is_free_correction)
                status_txt = "Gratuit (Accès libre)" if subject.is_free_correction else "Premium (Pass Semestre requis)"
                messages.success(request, f"Corrigés & résumés de l'UE « {subject.name} » basculés en mode : {status_txt}")

    return redirect("contributors:library_index")


@contributor_required
def exam_bulk_delete_published_view(request):
    """
    Supprime TOUTES les épreuves actuellement publiées sur le site ArchivEx (dans le contexte actif).
    PROTECTION ABSOLUE DU CLOUD STORAGE : Aucun fichier Cloud, aucun dossier, aucun fichier PDF physique
    ni aucune matière (Subject) n'est supprimé du Cloud Storage.
    Le Cloud Storage reste 100% intact et permanent.
    """
    if request.method == "POST":
        active_school, active_filiere, active_semester = get_active_academic_context(request)
        qs = Exam.objects.all()
        if active_school:
            qs = qs.filter(filiere__school=active_school)
        if active_filiere:
            qs = qs.filter(filiere=active_filiere)
        if active_semester:
            qs = qs.filter(semester=active_semester)

        count = qs.count()
        # Supprimer uniquement les publications (enregistrements Exam)
        # Les fichiers Cloud Storage restent 100% intacts (on_delete=SET_NULL)
        qs.delete()

        messages.success(
            request,
            f"Toutes les épreuves publiées ({count}) ont été supprimées du site public. Tous les fichiers originaux du Cloud Storage restent 100% conservés et intacts."
        )
    return redirect("contributors:exam_list")


@contributor_required
def library_exam_detail_view(request, pk):
    """Page de détail d'un fichier dans la Bibliothèque Cloud."""
    active_school, active_filiere, active_semester = get_active_academic_context(request)
    cloud_file = CloudFile.objects.filter(pk=pk).select_related("school", "filiere", "semester", "uploaded_by").first()

    exam = None
    if not cloud_file:
        exam = get_object_or_404(
            Exam.objects.select_related("subject", "semester", "filiere", "level", "academic_year", "filiere__school", "summary"),
            pk=pk
        )

    profile = getattr(request.user, "contributor_profile", None)
    is_main_admin = request.user.is_superuser or (profile and profile.role == "SUPER_ADMIN")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "cloud_file": cloud_file,
        "exam": exam,
        "is_main_admin": is_main_admin,
    }
    return render(request, "contributors/library/detail.html", context)


@contributor_required
def library_download_original_view(request, pk, file_type):
    """
    Récupération du fichier original non-filigrané par l'administrateur principal (SUPER_ADMIN).
    """
    profile = getattr(request.user, "contributor_profile", None)
    is_main_admin = request.user.is_superuser or (profile and profile.role == "SUPER_ADMIN")

    if not is_main_admin:
        return HttpResponseForbidden("Action de récupération d'original réservée à l'administrateur principal de la plateforme.")

    target_file = None
    cloud_file = CloudFile.objects.filter(pk=pk).first()
    if cloud_file and cloud_file.file:
        target_file = cloud_file.file
    else:
        exam = Exam.objects.filter(pk=pk).first()
        if exam:
            if file_type == "correction":
                target_file = exam.correction_file
            elif file_type == "summary":
                target_file = exam.summary_file or (exam.summary.file if exam.summary else None)
            else:
                target_file = exam.file

    if not target_file or not bool(target_file):
        raise Http404("Le fichier original réclamé est introuvable sur le serveur.")

    try:
        file_path = target_file.path
        if not os.path.exists(file_path):
            raise Http404("Le fichier physique original est introuvable sur le disque serveur.")
    except Exception:
        raise Http404("Fichier introuvable.")

    response = FileResponse(
        open(file_path, "rb"),
        content_type="application/pdf"
    )
    filename = os.path.basename(file_path)
    response["Content-Disposition"] = f'attachment; filename="ORIGINAL_{filename}"'
    return response


# ======================================================
# SUPPORT ÉTUDIANT — Délégation vers support.views
# Ces wrappers permettent de router via contributors.urls
# tout en maintenant la logique dans le module support.
# ======================================================

from support.views import admin_support_list_view, admin_support_detail_view

__all__ = [
    "admin_support_list_view",
    "admin_support_detail_view",
]
