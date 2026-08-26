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
    Système de Recherche Globale ArchivEx V2.
    Recherche unifiée à travers Matières, Épreuves, Résumés, Guides et Conseils.
    """
    from exams.models import Exam
    from content.models import Summary, Guide, Article

    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "all")

    subjects_results = []
    exams_results = []
    summaries_results = []
    guides_results = []
    articles_results = []

    total_results_count = 0

    if q:
        profile = getattr(request.user, "profile", None) if request.user.is_authenticated else None
        user_school = profile.school if profile else None
        user_filiere = profile.filiere if profile else None

        # 1. SUBJECTS
        if category in ["all", "subjects"]:
            subj_qs = Subject.objects.filter(
                Q(name__icontains=q) | Q(semester__filiere__name__icontains=q)
            ).select_related("semester", "semester__filiere", "semester__filiere__school", "semester__filiere__level")

            for s in subj_qs:
                is_priority = bool(user_filiere and s.semester.filiere_id == user_filiere.id)
                subjects_results.append({
                    "object": s,
                    "is_priority": is_priority,
                })
            subjects_results.sort(key=lambda x: not x["is_priority"])
            total_results_count += len(subjects_results)

        # 2. EXAMS
        if category in ["all", "exams"]:
            exam_qs = Exam.objects.filter(
                is_published=True
            ).filter(
                Q(title__icontains=q) | Q(subject__name__icontains=q) | Q(description__icontains=q)
            ).select_related("subject", "filiere", "level", "semester", "filiere__school")

            for ex in exam_qs:
                has_access = can_user_access(request.user, ex)
                is_priority = bool(user_filiere and ex.filiere_id == user_filiere.id)
                exams_results.append({
                    "object": ex,
                    "has_access": has_access,
                    "is_priority": is_priority,
                })
            exams_results.sort(key=lambda x: not x["is_priority"])
            total_results_count += len(exams_results)

        # 3. SUMMARIES
        if category in ["all", "summaries"]:
            sum_qs = Summary.objects.filter(
                publication_status="PUBLISHED"
            ).filter(
                Q(title__icontains=q) | Q(introduction__icontains=q) | Q(subject__name__icontains=q)
            ).select_related("subject", "subject__semester", "subject__semester__filiere", "author")

            for sm in sum_qs:
                has_access = can_user_access(request.user, sm)
                is_priority = bool(user_filiere and sm.subject.semester.filiere_id == user_filiere.id)
                summaries_results.append({
                    "object": sm,
                    "has_access": has_access,
                    "is_priority": is_priority,
                })
            summaries_results.sort(key=lambda x: not x["is_priority"])
            total_results_count += len(summaries_results)

        # 4. GUIDES
        if category in ["all", "guides"]:
            gd_qs = Guide.objects.filter(
                publication_status="PUBLISHED"
            ).filter(
                Q(title__icontains=q) | Q(introduction__icontains=q) | Q(subject__name__icontains=q)
            ).select_related("subject", "subject__semester", "subject__semester__filiere", "author")

            for gd in gd_qs:
                has_access = can_user_access(request.user, gd)
                is_priority = bool(user_filiere and gd.subject.semester.filiere_id == user_filiere.id)
                guides_results.append({
                    "object": gd,
                    "has_access": has_access,
                    "is_priority": is_priority,
                })
            guides_results.sort(key=lambda x: not x["is_priority"])
            total_results_count += len(guides_results)

        # 5. ARTICLES
        if category in ["all", "articles"]:
            art_qs = Article.objects.filter(
                publication_status="PUBLISHED"
            ).filter(
                Q(title__icontains=q) | Q(summary__icontains=q) | Q(content__icontains=q)
            ).select_related("target_school", "target_filiere", "author")

            for art in art_qs:
                articles_results.append({
                    "object": art,
                    "has_access": True,
                    "is_priority": bool(user_school and art.target_school_id == user_school.id),
                })
            articles_results.sort(key=lambda x: not x["is_priority"])
            total_results_count += len(articles_results)

    context = {
        "q": q,
        "selected_category": category,
        "subjects_results": subjects_results,
        "exams_results": exams_results,
        "summaries_results": summaries_results,
        "guides_results": guides_results,
        "articles_results": articles_results,
        "total_results_count": total_results_count,
        "profile": getattr(request.user, "profile", None) if request.user.is_authenticated else None,
    }
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




