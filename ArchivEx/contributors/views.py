import os
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.http import JsonResponse, HttpResponseForbidden, FileResponse, Http404

from academics.models import School, Level, Filiere, AcademicYear, Semester, Subject
from academics.parser import parse_exam_filename
from academics.ocr_utils import generate_pdf_summary_and_metadata
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
def check_exam_duplicate_api(request):
    """
    API JSON vérifiant en direct (AJAX) si une épreuve identique existe déjà.
    """
    title = request.GET.get("title", "").strip()
    subject_name = request.GET.get("subject_name", "").strip()
    semester_id = request.GET.get("semester_id")
    year_str = request.GET.get("year", "").strip()
    exam_type = request.GET.get("exam_type", "").strip()
    exclude_id = request.GET.get("exclude_id")

    if not title and not subject_name:
        return JsonResponse({"duplicate": False})

    qs = Exam.objects.select_related("subject", "semester", "filiere", "academic_year")
    if exclude_id and str(exclude_id).isdigit():
        qs = qs.exclude(pk=int(exclude_id))

    match = None
    if title:
        match = qs.filter(title__iexact=title).first()

    if not match and subject_name:
        sub_qs = qs.filter(subject__name__iexact=subject_name)
        if semester_id and str(semester_id).isdigit():
            sub_qs = sub_qs.filter(semester_id=int(semester_id))

        if year_str:
            extracted_digits = "".join([c for c in year_str if c.isdigit()])
            if len(extracted_digits) >= 4:
                first_4 = int(extracted_digits[:4])
                year_match_qs = sub_qs.filter(
                    Q(academic_year__label__icontains=year_str) |
                    Q(year=first_4)
                )
                if exam_type:
                    year_type_match = year_match_qs.filter(exam_type=exam_type).first()
                    if year_type_match:
                        match = year_type_match
                if not match:
                    match = year_match_qs.first()
        elif exam_type:
            match = sub_qs.filter(exam_type=exam_type).first()

    if match:
        return JsonResponse({
            "duplicate": True,
            "existing_id": match.id,
            "title": match.title,
            "subject": match.subject.name if match.subject else "Matière non spécifiée",
            "filiere": match.filiere.name if match.filiere else "",
            "semester": match.semester.label if match.semester else "",
            "academic_year": match.academic_year.label if match.academic_year else (str(match.year) if match.year else ""),
            "edit_url": f"/administration/epreuves/{match.id}/modifier/",
            "is_published": match.is_published,
        })

    return JsonResponse({"duplicate": False})


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

    # Chart data: Distribution des documents par filière (spécialité académique)
    filieres_qs = Filiere.objects.filter(school=active_school) if active_school else Filiere.objects.all()
    filieres_qs = filieres_qs.annotate(
        exams_cnt=Count('exams', distinct=True),
        summaries_cnt=Count('semesters__subjects__summaries', distinct=True),
        guides_cnt=Count('semesters__subjects__guides', distinct=True)
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
    })

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
        "filiere_chart_json": filiere_chart_json,
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

            # Vérification robuste des doublons
            duplicate_filter = Q(title__iexact=exam.title)
            if exam.subject and exam.semester:
                sub_sem_filter = Q(subject=exam.subject, semester=exam.semester, exam_type=exam.exam_type)
                if exam.academic_year:
                    sub_sem_filter &= (Q(academic_year=exam.academic_year) | Q(year=exam.year))
                elif exam.year:
                    sub_sem_filter &= Q(year=exam.year)
                duplicate_filter |= sub_sem_filter

            duplicate_match = Exam.objects.filter(duplicate_filter).select_related("subject", "semester", "filiere", "academic_year").first()

            if duplicate_match:
                if request.POST.get("replace_existing") == "1":
                    # Remplacement de l'épreuve existante avec les nouvelles informations et fichiers
                    duplicate_match.title = exam.title
                    duplicate_match.exam_type = exam.exam_type
                    duplicate_match.year = exam.year
                    if exam.academic_year:
                        duplicate_match.academic_year = exam.academic_year
                    duplicate_match.is_free = exam.is_free
                    duplicate_match.is_published = exam.is_published
                    if exam.description:
                        duplicate_match.description = exam.description

                    _process_exam_cloud_files(form, duplicate_match, target_semester, active_school, active_filiere, active_semester, request.user)
                    duplicate_match.save()

                    from accounts.utils import log_user_action
                    log_user_action(request, "MODIFICATION", f"Remplacement de l'épreuve existante #{duplicate_match.id} ({duplicate_match.title})")

                    messages.success(request, f"L'épreuve existante « {duplicate_match.title} » a été remplacée et mise à jour avec succès avec vos nouveaux fichiers !")
                    return redirect("contributors:exam_list")
                else:
                    # Blocage strict de la publication d'un doublon
                    context = {
                        "active_school": active_school,
                        "active_filiere": active_filiere,
                        "active_semester": active_semester,
                        "available_subjects": Subject.objects.filter(semester__filiere=active_filiere).select_related("semester") if active_filiere else Subject.objects.none(),
                        "form": form,
                        "is_create": True,
                        "duplicate_warning": True,
                        "existing_duplicate": duplicate_match,
                    }
                    messages.error(request, f"Publication impossible : Une épreuve identique existe déjà dans la base (« {duplicate_match.title} » pour {duplicate_match.subject.name}). Vous devez soit remplacer l'épreuve existante, soit modifier les informations.")
                    return render(request, "contributors/exams/form.html", context)

            # Traitement des fichiers Cloud et téléversements directs
            _process_exam_cloud_files(form, exam, target_semester, active_school, active_filiere, active_semester, request.user)

            exam.save()

            status_str = "publiée" if exam.is_published else "enregistrée en brouillon"
            messages.success(request, f"Épreuve « {exam.title} » {status_str} avec succès pour {exam.subject.name}.")
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
        "duplicate_warning": False,
        "existing_duplicate": None,
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

            # Vérification des doublons (en excluant l'épreuve courante)
            duplicate_exists = Exam.objects.filter(
                title__iexact=exam.title,
                subject=exam.subject,
                academic_year=exam.academic_year,
                semester=exam.semester
            ).exclude(pk=exam.pk).exists()

            if duplicate_exists:
                form.add_error("title", f"Une autre épreuve nommée « {exam.title} » existe déjà pour cette matière.")
            else:
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

    published_exam_map = dict(
        Exam.objects.filter(cloud_file__in=cloud_files).values_list("cloud_file_id", "id")
    )

    grouped_cloud_files = {}
    for cf in cloud_files:
        parsed = parse_exam_filename(cf.title, available_subjects=available_subjects)
        cf.parsed_info = parsed
        cf.published_exam_id = published_exam_map.get(cf.id)
        cf.is_already_published = bool(cf.published_exam_id)
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

    total_size_bytes = 0
    for cf in CloudFile.objects.all():
        if cf.file:
            try:
                total_size_bytes += cf.file.size
            except Exception:
                total_size_bytes += 1200000
        else:
            total_size_bytes += 1200000

    LIMIT_BYTES = 100 * 1024 * 1024  # 100 MB limit
    total_size_mb = round(total_size_bytes / (1024 * 1024), 1)
    limit_mb = round(LIMIT_BYTES / (1024 * 1024), 1)
    fill_percentage = min(100.0, round((total_size_bytes / LIMIT_BYTES) * 100, 1))

    # Retrieve lists for bulk displacement options
    filieres_list = Filiere.objects.filter(school=active_school) if active_school else Filiere.objects.all()
    semesters_list = Semester.objects.filter(filiere__school=active_school) if active_school else Semester.objects.all()

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
        "total_size_mb": total_size_mb,
        "limit_mb": limit_mb,
        "fill_percentage": fill_percentage,
        "filieres_list": filieres_list,
        "semesters_list": semesters_list,
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

    # Extraire automatiquement le texte et générer un résumé via OCR Python si aucune méta-donnée n'est détectée
    ocr_result = None
    auto_ocr_summary = ""
    force_ocr_flag = request.GET.get("force_ocr") == "1"

    if (not parsed.get("is_valid") or not detected_subject_name or not detected_academic_year or force_ocr_flag) and cloud_file.file:
        try:
            ocr_result = generate_pdf_summary_and_metadata(
                cloud_file.file,
                filename=cloud_file.title,
                available_subjects=available_subjects,
                force_ocr=force_ocr_flag
            )
            auto_ocr_summary = ocr_result.get("summary", "")

            # Si la matière ou l'année manque, utiliser le résultat OCR s'il est disponible
            if not detected_subject_name and ocr_result.get("detected_subject_name"):
                detected_subject_name = ocr_result["detected_subject_name"]
            if not detected_academic_year and ocr_result.get("detected_year"):
                detected_academic_year = ocr_result["detected_year"]
        except Exception as ocr_err:
            logger.warning(f"Erreur d'extraction OCR dans publish_from_cloud_view: {ocr_err}")

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

            # Duplicate check
            duplicate_filter = Q(title__iexact=exam.title) | Q(cloud_file=cloud_file)
            if cloud_file and cloud_file.file:
                duplicate_filter |= Q(file=cloud_file.file)
            if exam.subject and exam.semester:
                sub_sem_filter = Q(subject=exam.subject, semester=exam.semester, exam_type=exam.exam_type)
                if exam.academic_year:
                    sub_sem_filter &= (Q(academic_year=exam.academic_year) | Q(year=exam.year))
                elif exam.year:
                    sub_sem_filter &= Q(year=exam.year)
                duplicate_filter |= sub_sem_filter

            duplicate_match = Exam.objects.filter(duplicate_filter).select_related("subject", "semester", "filiere", "academic_year").first()

            if duplicate_match:
                if request.POST.get("replace_existing") == "1":
                    duplicate_match.title = exam.title
                    duplicate_match.exam_type = exam.exam_type
                    duplicate_match.year = exam.year
                    if exam.academic_year:
                        duplicate_match.academic_year = exam.academic_year
                    duplicate_match.is_free = exam.is_free
                    duplicate_match.is_published = exam.is_published
                    if exam.description:
                        duplicate_match.description = exam.description

                    _process_exam_cloud_files(form, duplicate_match, target_semester, active_school, target_filiere, active_semester, request.user)
                    duplicate_match.save()

                    from accounts.utils import log_user_action
                    log_user_action(request, "MODIFICATION", f"Remplacement de l'épreuve existante #{duplicate_match.id} ({duplicate_match.title}) depuis le Cloud Storage")

                    messages.success(request, f"L'épreuve existante « {duplicate_match.title} » a été remplacée et mise à jour avec succès avec vos nouveaux fichiers !")
                    return redirect("contributors:exam_list")
                else:
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
                        "ocr_result": ocr_result,
                        "auto_ocr_summary": auto_ocr_summary,
                        "no_metadata_detected": not parsed.get("is_valid", False),
                        "duplicate_warning": True,
                        "existing_duplicate": duplicate_match,
                    }
                    messages.error(request, f"Publication impossible : Une épreuve identique existe déjà dans la base (« {duplicate_match.title} » pour {duplicate_match.subject.name}). Vous devez soit remplacer l'épreuve existante, soit modifier les informations.")
                    return render(request, "contributors/exams/form.html", context)

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
            "exam_type": (ocr_result.get("detected_exam_type") if ocr_result else "examen") or "examen",
            "description": auto_ocr_summary or "",
            "is_published": "True",
            "is_free": "False",
            "cloud_file": cloud_file if cloud_file.file_type == "EXAM" else None,
            "cloud_correction_file": cloud_file if cloud_file.file_type == "CORRECTION" else auto_corr_cloud,
            "cloud_summary_file": cloud_file if cloud_file.file_type == "SUMMARY" else auto_sum_cloud,
            "semester": cloud_file.semester or active_semester,
        }
        form = ExamAdminForm(initial=form_initial, active_filiere=target_filiere, active_semester=cloud_file.semester or active_semester)

    # Détection dès l'ouverture du formulaire si ce document Cloud ou titre existe déjà
    pre_dup_filter = Q(cloud_file=cloud_file)
    if cloud_file.file:
        pre_dup_filter |= Q(file=cloud_file.file)
    if initial_title:
        pre_dup_filter |= Q(title__iexact=initial_title)
    if detected_subject_name and (cloud_file.semester or active_semester):
        sem_cand = cloud_file.semester or active_semester
        pre_dup_filter |= Q(subject__name__iexact=detected_subject_name, semester=sem_cand)

    existing_duplicate_on_get = Exam.objects.filter(pre_dup_filter).select_related("subject", "semester", "filiere", "academic_year").first()
    if existing_duplicate_on_get and request.method != "POST":
        messages.warning(
            request,
            f"Attention : Ce fichier Cloud est déjà associé à l'épreuve « {existing_duplicate_on_get.title} » ({existing_duplicate_on_get.subject.name}). Vous pouvez remplacer l'épreuve existante ci-dessous ou modifier les informations."
        )

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
        "ocr_result": ocr_result,
        "auto_ocr_summary": auto_ocr_summary,
        "no_metadata_detected": not parsed.get("is_valid", False),
        "duplicate_warning": bool(existing_duplicate_on_get),
        "existing_duplicate": existing_duplicate_on_get,
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
        yr_label = parsed["detected_academic_year"] or "2025-2026"
        if "-" in yr_label:
            ay_obj, _ = AcademicYear.objects.get_or_create(label=yr_label)
            yr_int = int(yr_label.split("-")[1])
        else:
            yr_int = 2025
            ay_obj = target_semester.academic_year or AcademicYear.objects.first()

        exam_title = cf.title.replace("Épreuve — ", "").replace(".pdf", "").strip()

        # Recherche avancée anti-doublon : par CloudFile, par fichier ou par titre/matière/semestre/année
        dup_filter = Q(title__iexact=exam_title) | Q(cloud_file=cf)
        if cf.file:
            dup_filter |= Q(file=cf.file)
        if subject and target_semester:
            dup_filter |= Q(subject=subject, semester=target_semester, exam_type="examen", year=yr_int)

        existing_exam = Exam.objects.filter(dup_filter).first()

        # Recherche du corrigé correspondant parmi les fichiers de cette même UE
        corr_cf = None
        for c_cf, c_parsed in matching_cloud_corrections:
            if c_parsed["clean_title"] == parsed["clean_title"] or cf.title in c_cf.title or subject.name in c_cf.title:
                corr_cf = c_cf
                break

        if existing_exam:
            # Mettre à jour l'épreuve existante SANS créer de doublon
            existing_exam.is_published = True
            if not existing_exam.file and cf.file:
                existing_exam.file = cf.file
            if not existing_exam.cloud_file:
                existing_exam.cloud_file = cf
            if corr_cf:
                if not existing_exam.cloud_correction_file:
                    existing_exam.cloud_correction_file = corr_cf
                if not existing_exam.correction_file and corr_cf.file:
                    existing_exam.correction_file = corr_cf.file
            existing_exam.save()
            published_count += 1
            if existing_exam.has_correction:
                with_corr_count += 1
            continue

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
from accounts.models import SiteLog
from django.core.paginator import Paginator

@contributor_required
def site_logs_list_view(request):
    """Affiche le journal d'activité complet du site, filtrable par type d'action."""
    active_school, active_filiere, active_semester = None, None, None
    try:
        active_school, active_filiere, active_semester = get_active_academic_context(request)
    except Exception:
        pass
    
    # Récupération des filtres
    action_filter = request.GET.get("action_type", "")
    search_q = request.GET.get("q", "").strip()
    
    try:
        logs_qs = SiteLog.objects.select_related("user").order_by("-created_at")
        
        if action_filter:
            logs_qs = logs_qs.filter(action_type=action_filter)
            
        if search_q:
            logs_qs = logs_qs.filter(
                Q(description__icontains=search_q) |
                Q(user__username__icontains=search_q) |
                Q(path__icontains=search_q) |
                Q(ip_address__icontains=search_q)
            )
            
        # Pagination (50 logs par page)
        paginator = Paginator(logs_qs, 50)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
        
        # Statistiques pour les KPI du journal
        total_logs = SiteLog.objects.count()
        connections_count = SiteLog.objects.filter(action_type="CONNECTION").count()
        modifications_count = SiteLog.objects.filter(action_type="MODIFICATION").count()
        clicks_count = SiteLog.objects.filter(action_type="CLICK").count()
        views_count = SiteLog.objects.filter(action_type="PAGE_VIEW").count()
    except Exception as e:
        empty_paginator = Paginator([], 50)
        page_obj = empty_paginator.get_page(1)
        total_logs = 0
        connections_count = 0
        modifications_count = 0
        clicks_count = 0
        views_count = 0
        messages.warning(request, f"Note: Le journal d'activité n'est pas encore initialisé ou une migration est requise ({str(e)}).")

    context = {
        "active_school": active_school,
        "active_filiere": active_filiere,
        "active_semester": active_semester,
        "page_obj": page_obj,
        "action_filter": action_filter,
        "search_q": search_q,
        "total_logs": total_logs,
        "connections_count": connections_count,
        "modifications_count": modifications_count,
        "clicks_count": clicks_count,
        "views_count": views_count,
        "action_choices": getattr(SiteLog, "ACTION_CHOICES", ()),
    }
    template_names = [
        "contributors/logs/list.html",
        "contributors/site_logs/list.html",
        "contributors/site_logs/index.html",
    ]
    return render(request, template_names, context)


@contributor_required
def export_logs_pdf_view(request):
    """Génère un export PDF professionnel du journal des activités avec filtres appliqués."""
    try:
        import io
        from django.http import HttpResponse
        from django.utils import timezone
        from django.db.models import Q
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.pdfgen import canvas
        
        # Récupération des mêmes filtres que la vue de liste
        action_filter = request.GET.get("action_type", "")
        search_q = request.GET.get("q", "").strip()
        
        logs_qs = SiteLog.objects.select_related("user").order_by("-created_at")
        
        if action_filter:
            logs_qs = logs_qs.filter(action_type=action_filter)
            
        if search_q:
            logs_qs = logs_qs.filter(
                Q(description__icontains=search_q) |
                Q(user__username__icontains=search_q) |
                Q(path__icontains=search_q) |
                Q(ip_address__icontains=search_q)
            )
            
        # Limiter à un nombre raisonnable de logs (par exemple, les 1000 derniers) pour éviter le dépassement de mémoire
        logs_qs = logs_qs[:1000]
        
        # Création du flux PDF en mémoire
        buffer = io.BytesIO()
        
        # Document A4 Paysage
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=54,
            rightMargin=54,
            topMargin=72,
            bottomMargin=72
        )
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#071A49"),
            spaceAfter=6
        )
        
        subtitle_style = ParagraphStyle(
            'DocSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=15
        )
        
        cell_style = ParagraphStyle(
            'TableCell',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1e293b")
        )
        
        header_cell_style = ParagraphStyle(
            'TableHeaderCell',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.white
        )
        
        story = []
        
        # Titre principal
        story.append(Paragraph("ArchivEx — Journal d'Activité et d'Audit", title_style))
        
        # Infos de métadonnées
        now_str = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
        filters_desc = "Aucun"
        if action_filter or search_q:
            filters_desc = f"Action: {action_filter or 'Tous'} | Recherche: '{search_q or ''}'"
        
        sub_text = (
            f"Généré le : {now_str} par l'administrateur @{request.user.username}<br/>"
            f"Filtres appliqués : {filters_desc} · (Affichage limité aux 1 000 dernières entrées)"
        )
        story.append(Paragraph(sub_text, subtitle_style))
        story.append(Spacer(1, 10))
        
        # Table des logs
        table_data = [[
            Paragraph("Horodatage", header_cell_style),
            Paragraph("Type d'action", header_cell_style),
            Paragraph("Utilisateur", header_cell_style),
            Paragraph("Description / Détails de l'action", header_cell_style),
            Paragraph("Adresse IP", header_cell_style)
        ]]
        
        for log in logs_qs:
            log_time = log.created_at.strftime("%d/%m/%Y %H:%M:%S")
            username = log.user.username if log.user else "Visiteur Public"
            
            # Color coding text for action type
            if log.action_type == 'CONNECTION':
                action_html = "<font color='#2563eb'><b>CONNEXION</b></font>"
            elif log.action_type == 'MODIFICATION':
                action_html = "<font color='#10b981'><b>MODIFICATION</b></font>"
            elif log.action_type == 'CLICK':
                action_html = "<font color='#d97706'><b>CLIC D'ICÔNE</b></font>"
            else:
                action_html = "<font color='#7c3aed'><b>PAGE LUE</b></font>"
                
            desc_text = log.description
            if log.path:
                desc_text += f"<br/><font color='#64748b' size='7'><b>Ressource :</b> {log.path}</font>"
                
            table_data.append([
                Paragraph(log_time, cell_style),
                Paragraph(action_html, cell_style),
                Paragraph(username, cell_style),
                Paragraph(desc_text, cell_style),
                Paragraph(log.ip_address or "127.0.0.1", cell_style)
            ])
            
        # Table widths
        col_widths = [110, 85, 100, 340, 98]
        
        # Table styling
        logs_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        logs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#071A49")),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        
        story.append(logs_table)
        
        # Custom NumberedCanvas local class definition to draw headers/footers
        class NumberedCanvas(canvas.Canvas):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._saved_page_states = []

            def showPage(self):
                self._saved_page_states.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                num_pages = len(self._saved_page_states)
                for state in self._saved_page_states:
                    self.__dict__.update(state)
                    self.draw_page_decorations(num_pages)
                    super().showPage()
                super().save()

            def draw_page_decorations(self, page_count):
                self.saveState()
                self.setFont("Helvetica-Bold", 8)
                self.setFillColor(colors.HexColor("#071A49"))
                
                # Header
                self.drawString(54, 555, "ArchivEx — Rapport d'Audit & Journal de Télémétrie")
                self.setFont("Helvetica", 8)
                self.setFillColor(colors.HexColor("#64748b"))
                self.drawRightString(788, 555, f"Filtres : {action_filter or 'Tous'}")
                
                self.setStrokeColor(colors.HexColor("#e2e8f0"))
                self.setLineWidth(0.5)
                self.line(54, 547, 788, 547)
                
                # Footer
                self.line(54, 45, 788, 45)
                page_text = f"Page {self._pageNumber} sur {page_count}"
                self.drawRightString(788, 30, page_text)
                self.drawString(54, 30, "Document officiel confidentiel réservé aux administrateurs ArchivEx")
                self.restoreState()
                
        doc.build(story, canvasmaker=NumberedCanvas)
        
        # Récupération du PDF
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"Journal_Audit_ArchivEx_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        messages.error(request, f"Impossible de générer l'export PDF du journal : {str(e)}")
        return redirect("contributors:site_logs_list")


@contributor_required
def bulk_operations_view(request):
    """
    Gère les actions groupées (publication, suppression, déplacement) pour une sélection de fichiers Cloud.
    """
    if request.method != "POST":
        return redirect("contributors:library_index")

    action = request.POST.get("action")
    selected_ids = request.POST.getlist("selected_files")

    if not selected_ids:
        messages.warning(request, "Aucun fichier n'a été sélectionné.")
        return redirect("contributors:library_index")

    selected_files = CloudFile.objects.filter(pk__in=selected_ids)
    count = selected_files.count()

    if action == "delete":
        # Suppression en masse (BD + fichiers physiques si existants)
        for cf in selected_files:
            if cf.file:
                cf.file.delete(save=False)
            cf.delete()
        messages.success(request, f"{count} fichier(s) supprimé(s) avec succès de la bibliothèque Cloud.")

    elif action == "move":
        # Déplacement en masse (changement de filière et/ou semestre)
        dest_filiere_id = request.POST.get("dest_filiere")
        dest_semester_id = request.POST.get("dest_semester")

        if not dest_filiere_id and not dest_semester_id:
            messages.error(request, "Veuillez sélectionner au moins une filière ou un semestre de destination.")
            return redirect("contributors:library_index")

        filiere_obj = None
        semester_obj = None

        if dest_filiere_id:
            filiere_obj = Filiere.objects.filter(pk=dest_filiere_id).first()
        if dest_semester_id:
            semester_obj = Semester.objects.filter(pk=dest_semester_id).first()

        # Déduire la filière du semestre si nécessaire
        if semester_obj and not filiere_obj:
            filiere_obj = semester_obj.filiere

        for cf in selected_files:
            if filiere_obj:
                cf.filiere = filiere_obj
            if semester_obj:
                cf.semester = semester_obj
            cf.save()

        dest_name = f"{filiere_obj.name if filiere_obj else ''} {f'({semester_obj.label})' if semester_obj else ''}".strip()
        messages.success(request, f"{count} fichier(s) déplacé(s) vers « {dest_name} » avec succès.")

    elif action == "publish":
        # Publication en masse des fichiers sélectionnés
        published_exams = 0
        published_corrections = 0
        published_summaries = 0
        
        # On fait une passe pour regrouper les épreuves et les corrigés rattachables
        exams_to_process = []
        corrections_to_process = []
        summaries_to_process = []

        for cf in selected_files:
            if cf.file_type == "EXAM":
                exams_to_process.append(cf)
            elif cf.file_type == "CORRECTION":
                corrections_to_process.append(cf)
            elif cf.file_type == "SUMMARY":
                summaries_to_process.append(cf)
            else:
                exams_to_process.append(cf)

        # 1. Traitement des Résumés (SUMMARY)
        for cf in summaries_to_process:
            parsed = parse_exam_filename(cf.title)
            ue_name = parsed["matched_subject"].name if parsed["matched_subject"] else (parsed["subject_candidate"] or "Autre UE")
            
            target_semester = cf.semester or Semester.objects.first()
            subject, _ = Subject.objects.get_or_create(
                name=ue_name.strip(),
                semester=target_semester,
                defaults={"is_active": True}
            )
            
            clean_title = cf.title.replace("Résumé — ", "").replace(".pdf", "").strip()
            Summary.objects.create(
                title=clean_title,
                subject=subject,
                file=cf.file if cf.file else None,
                introduction=f"Résumé de cours de l'UE {subject.name}.",
                content=f"<p>Résumé PDF téléchargeable pour l'UE {subject.name}.</p>",
                publication_status="PUBLISHED",
                access_type="PREMIUM",
            )
            published_summaries += 1
            cf.delete()

        # 2. Traitement des Examens (EXAM)
        for cf in exams_to_process:
            parsed = parse_exam_filename(cf.title)
            ue_name = parsed["matched_subject"].name if parsed["matched_subject"] else (parsed["subject_candidate"] or "Autre UE")
            
            target_semester = cf.semester or Semester.objects.first()
            subject, _ = Subject.objects.get_or_create(
                name=ue_name.strip(),
                semester=target_semester,
                defaults={"is_active": True}
            )

            yr_label = parsed["detected_academic_year"] or "2025-2026"
            if "-" in yr_label:
                ay_obj, _ = AcademicYear.objects.get_or_create(label=yr_label)
                yr_int = int(yr_label.split("-")[1])
            else:
                yr_int = 2025
                ay_obj = target_semester.academic_year or AcademicYear.objects.first()

            # Est-ce qu'on a un corrigé correspondant sélectionné dans corrections_to_process ?
            corr_cf = None
            for ccf in corrections_to_process:
                if subject.name.lower() in ccf.title.lower() or parsed["clean_title"] in ccf.title:
                    corr_cf = ccf
                    corrections_to_process.remove(ccf)
                    break

            exam_title = cf.title.replace("Épreuve — ", "").replace(".pdf", "").strip()
            Exam.objects.create(
                title=exam_title,
                subject=subject,
                semester=target_semester,
                filiere=target_semester.filiere if target_semester else None,
                level=target_semester.filiere.level if (target_semester and target_semester.filiere) else None,
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
            published_exams += 1

        # 3. Traitement des Corrections orphelines
        for cf in corrections_to_process:
            parsed = parse_exam_filename(cf.title)
            ue_name = parsed["matched_subject"].name if parsed["matched_subject"] else (parsed["subject_candidate"] or "Autre UE")
            
            target_semester = cf.semester or Semester.objects.first()
            subject, _ = Subject.objects.get_or_create(
                name=ue_name.strip(),
                semester=target_semester,
                defaults={"is_active": True}
            )

            existing_exam = Exam.objects.filter(subject=subject, correction_file__isnull=True).first()
            if existing_exam:
                existing_exam.cloud_correction_file = cf
                existing_exam.correction_file = cf.file if cf.file else None
                existing_exam.is_published = True
                existing_exam.save()
            else:
                yr_label = parsed["detected_academic_year"] or "2025-2026"
                if "-" in yr_label:
                    ay_obj, _ = AcademicYear.objects.get_or_create(label=yr_label)
                    yr_int = int(yr_label.split("-")[1])
                else:
                    yr_int = 2025
                    ay_obj = target_semester.academic_year or AcademicYear.objects.first()

                exam_title = cf.title.replace("Correction — ", "").replace(".pdf", "").strip()
                Exam.objects.create(
                    title=exam_title,
                    subject=subject,
                    semester=target_semester,
                    filiere=target_semester.filiere if target_semester else None,
                    level=target_semester.filiere.level if (target_semester and target_semester.filiere) else None,
                    academic_year=ay_obj,
                    year=yr_int,
                    exam_type="correction",
                    cloud_file=None,
                    file=None,
                    cloud_correction_file=cf,
                    correction_file=cf.file if cf.file else None,
                    is_free=subject.is_free,
                    is_free_correction=subject.is_free_correction,
                    is_published=True,
                )
            published_corrections += 1

        messages.success(
            request,
            f"Publication groupée terminée : {published_exams} épreuve(s), {published_corrections} corrigé(s) et {published_summaries} résumé(s) ont été rattachés et publiés."
        )

    return redirect("contributors:library_index")


@contributor_required
def extract_pdf_ocr_view(request, pk):
    """
    Extrait le texte d'un fichier Cloud via PyPDF / OCR Python et génère un résumé automatique.
    Retourne une réponse JSON (pour AJAX) ou effectue une redirection.
    """
    cloud_file = get_object_or_404(CloudFile, pk=pk)
    force_ocr = request.GET.get("force_ocr") == "1" or request.POST.get("force_ocr") == "1"

    target_filiere = cloud_file.filiere
    available_subjects = Subject.objects.filter(semester__filiere=target_filiere) if target_filiere else Subject.objects.all()

    if not cloud_file.file:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({"success": False, "error": "Aucun fichier PDF rattaché à ce document Cloud."}, status=400)
        messages.error(request, "Aucun fichier PDF rattaché à ce document Cloud.")
        return redirect("contributors:library_detail", pk=pk)

    try:
        res = generate_pdf_summary_and_metadata(
            cloud_file.file,
            filename=cloud_file.title,
            available_subjects=available_subjects,
            force_ocr=force_ocr
        )

        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({
                "success": True,
                "file_id": cloud_file.id,
                "title": cloud_file.title,
                "summary": res["summary"],
                "extracted_text": res["extracted_text"],
                "used_ocr": res["used_ocr"],
                "detected_subject": res["detected_subject_name"],
                "detected_year": res["detected_year"],
                "detected_exam_type": res["detected_exam_type"],
                "detected_tags": res.get("detected_tags", []),
                "tags_str": res.get("tags_str", ""),
                "char_count": res["extracted_text_length"],
            })

        messages.success(
            request,
            f"Extraction PDF/OCR réussie pour « {cloud_file.title} » ({res['extracted_text_length']} caractères analysés, OCR={'Oui' if res['used_ocr'] else 'Non'})."
        )
        return redirect("contributors:publish_from_cloud", pk=pk)

    except Exception as e:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({"success": False, "error": f"Erreur d'extraction OCR : {str(e)}"}, status=500)
        messages.error(request, f"Erreur lors de l'extraction OCR : {str(e)}")
        return redirect("contributors:library_detail", pk=pk)


@contributor_required
def extract_uploaded_pdf_ocr_view(request):
    """
    Extrait le texte et génère un résumé court depuis un fichier PDF directement téléversé (AJAX).
    """
    if request.method != "POST" or "pdf_file" not in request.FILES:
        return JsonResponse({"success": False, "error": "Veuillez fournir un fichier PDF valide."}, status=400)

    pdf_file = request.FILES["pdf_file"]
    force_ocr = request.POST.get("force_ocr") == "1"

    try:
        res = generate_pdf_summary_and_metadata(
            pdf_file,
            filename=pdf_file.name,
            available_subjects=Subject.objects.all(),
            force_ocr=force_ocr
        )

        return JsonResponse({
            "success": True,
            "filename": pdf_file.name,
            "summary": res["summary"],
            "extracted_text": res["extracted_text"],
            "used_ocr": res["used_ocr"],
            "detected_subject": res["detected_subject_name"],
            "detected_year": res["detected_year"],
            "detected_exam_type": res["detected_exam_type"],
            "detected_tags": res.get("detected_tags", []),
            "tags_str": res.get("tags_str", ""),
            "char_count": res["extracted_text_length"],
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Erreur lors de l'analyse du PDF : {str(e)}"}, status=500)


@contributor_required
def admin_settings_view(request):
    """
    Page des paramètres d'administration et sélection de la palette d'accentuation professionnelle.
    """
    school_ctx, filiere_ctx, semester_ctx = get_active_academic_context(request)
    context = {
        "active_school": school_ctx,
        "active_filiere": filiere_ctx,
        "active_semester": semester_ctx,
    }
    return render(request, "contributors/settings.html", context)


__all__ = [
    "admin_support_list_view",
    "admin_support_detail_view",
    "site_logs_list_view",
    "export_logs_pdf_view",
    "bulk_operations_view",
    "extract_pdf_ocr_view",
    "extract_uploaded_pdf_ocr_view",
    "admin_settings_view",
]
