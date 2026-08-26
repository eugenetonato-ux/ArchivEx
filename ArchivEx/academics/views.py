from django.shortcuts import render, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from .models import School, Level, Filiere, Semester, Subject
from exams.models import Exam
from payments.models import SemesterAccess

User = get_user_model()


def home_view(request):
    """Page d'accueil (Landing Page) accessible à tous."""
    schools_count = School.objects.filter(is_active=True).count()
    filieres_count = Filiere.objects.count()
    subjects_count = Subject.objects.count()
    exams_count = Exam.objects.filter(is_published=True).count()
    students_count = User.objects.filter(is_staff=False).count()

    featured_filieres = Filiere.objects.select_related("school", "level").annotate(
        exams_num=Count("exams")
    )[:6]

    latest_exams = Exam.objects.filter(
        is_published=True
    ).select_related("subject", "semester", "filiere", "level")[:6]

    context = {
        "schools_count": schools_count,
        "filieres_count": filieres_count,
        "subjects_count": subjects_count,
        "exams_count": exams_count,
        "students_count": students_count,
        "featured_filieres": featured_filieres,
        "latest_exams": latest_exams,
    }
    return render(request, "academics/home.html", context)


def about_view(request):
    """Page À propos d'ArchivEx accessible à tous."""
    return render(request, "academics/about.html")


from subscriptions.services import can_user_access


@login_required
def filiere_list_view(request):
    """
    Vue principale UE ("Mes UE").
    Charge DIRECTEMENT les UE correspondant au contexte académique de l'étudiant connecté
    (École + Filière + Niveau + Semestre), sans AUCUNE étape intermédiaire de choix de filière !
    """
    profile = getattr(request.user, "profile", None)
    
    semester = None
    subjects = []
    has_semester_access = False
    filiere = None
    total_exams_count = 0
    premium_exams_count = 0

    if profile and profile.filiere:
        filiere = profile.filiere
        semester = Semester.objects.filter(filiere=profile.filiere).first()
    else:
        active_access = SemesterAccess.objects.filter(
            Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status="reussi"))
        ).select_related("filiere", "semester").first()
        if active_access:
            filiere = active_access.filiere
            semester = active_access.semester
        else:
            filiere = Filiere.objects.first()

    if not semester and filiere:
        semester = Semester.objects.filter(filiere=filiere).first()

    if semester:
        subjects = Subject.objects.filter(semester=semester).annotate(
            exams_num=Count("exams")
        )
        has_semester_access = can_user_access(request.user, semester)

        total_exams_count = Exam.objects.filter(semester=semester, is_published=True).count()
        premium_exams_count = Exam.objects.filter(semester=semester, is_published=True, is_free=False).count()

    context = {
        "profile": profile,
        "filiere": filiere,
        "semester": semester,
        "subjects": subjects,
        "has_semester_access": has_semester_access,
        "total_exams_count": total_exams_count,
        "premium_exams_count": premium_exams_count,
    }
    return render(request, "academics/matieres.html", context)


@login_required
def semester_list_view(request, filiere_id):
    """Page listant les semestres d'une filière avec counts réels et statut d'accès."""
    from exams.models import Exam
    from content.models import Summary, Guide

    filiere = get_object_or_404(Filiere.objects.select_related("school", "level"), pk=filiere_id)
    semesters = Semester.objects.filter(filiere=filiere).select_related("academic_year").annotate(
        subjects_num=Count("subjects")
    )

    semesters_data = []
    for sem in semesters:
        exams_count = Exam.objects.filter(semester=sem, is_published=True).count()
        summaries_count = Summary.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()
        guides_count = Guide.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()

        semesters_data.append({
            "semester": sem,
            "has_access": can_user_access(request.user, sem),
            "subjects_num": sem.subjects_num,
            "exams_count": exams_count,
            "summaries_count": summaries_count,
            "guides_count": guides_count,
        })

    context = {
        "filiere": filiere,
        "semesters_data": semesters_data,
        "profile": getattr(request.user, "profile", None),
    }
    return render(request, "academics/semestres.html", context)


@login_required
def subject_list_view(request, semester_id):
    """Page listant les UE d'un semestre spécifié avec counts par ressource."""
    from exams.models import Exam
    from content.models import Summary, Guide

    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    subjects = Subject.objects.filter(semester=semester)

    subjects_data = []
    for subj in subjects:
        e_count = Exam.objects.filter(subject=subj, is_published=True).count()
        s_count = Summary.objects.filter(subject=subj, publication_status="PUBLISHED").count()
        g_count = Guide.objects.filter(subject=subj, publication_status="PUBLISHED").count()
        subjects_data.append({
            "subject": subj,
            "exams_count": e_count,
            "summaries_count": s_count,
            "guides_count": g_count,
        })

    has_semester_access = can_user_access(request.user, semester)

    total_exams_count = Exam.objects.filter(semester=semester, is_published=True).count()
    premium_exams_count = Exam.objects.filter(semester=semester, is_published=True, is_free=False).count()

    context = {
        "semester": semester,
        "filiere": semester.filiere,
        "subjects_data": subjects_data,
        "subjects": subjects,
        "has_semester_access": has_semester_access,
        "total_exams_count": total_exams_count,
        "premium_exams_count": premium_exams_count,
        "profile": getattr(request.user, "profile", None),
    }
    return render(request, "academics/matieres.html", context)


def global_search_view(request):
    """
    Système de Recherche Globale Intelligent ArchivEx V2.
    Délègue la recherche intelligente (mots partiels, tolérance aux accents,
    singulier/pluriel et scoring de pertinence) à academics.search.
    """
    from academics.search import execute_intelligent_search

    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "all")

    context = execute_intelligent_search(query_string=q, category=category, user=request.user)
    context["profile"] = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    return render(request, "search/global_search.html", context)


def custom_403_view(request, exception=None):
    """Vue d'erreur 403 personnalisée (Accès refusé)."""
    return render(request, "403.html", status=403)


def custom_404_view(request, exception=None):
    """Vue d'erreur 404 personnalisée (Page introuvable)."""
    return render(request, "404.html", status=404)


def custom_500_view(request):
    """Vue d'erreur 500 personnalisée (Erreur serveur)."""
    return render(request, "500.html", status=500)




