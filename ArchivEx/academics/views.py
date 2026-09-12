from django.shortcuts import render, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.core.cache import cache
from .models import School, Level, Filiere, Semester, Subject, SiteConfiguration
from exams.models import Exam
from payments.models import SemesterAccess
from content.models import Summary, Guide
from subscriptions.services import can_user_access

User = get_user_model()


def home_view(request):
    """
    Page d'accueil (Landing Page) accessible à tous.
    Optimisée avec un cache mémoire haute vitesse pour garantir un temps de réponse < 100ms.
    """
    cache_key = "archivex_home_stats_and_showcase"
    cached_data = cache.get(cache_key)

    if not cached_data:
        schools_count = School.objects.filter(is_active=True).count()
        filieres_count = Filiere.objects.count()
        subjects_count = Subject.objects.count()
        exams_count = Exam.objects.filter(is_published=True).count()
        summaries_count = Summary.objects.filter(publication_status="PUBLISHED").count()
        guides_count = Guide.objects.filter(publication_status="PUBLISHED").count()
        students_count = User.objects.filter(is_staff=False).count()
        passes_count = SemesterAccess.objects.filter(activated_at__isnull=False).count()

        featured_filieres = list(
            Filiere.objects.select_related("school", "level").annotate(
                exams_num=Count("exams", distinct=True)
            )[:6]
        )

        latest_exams = list(
            Exam.objects.filter(
                is_published=True
            ).select_related("subject", "semester", "filiere", "level", "filiere__school")[:6]
        )

        latest_summaries = list(
            Summary.objects.filter(
                publication_status="PUBLISHED"
            ).select_related("subject", "subject__semester", "subject__semester__filiere")[:6]
        )

        cached_data = {
            "schools_count": schools_count,
            "filieres_count": filieres_count,
            "subjects_count": subjects_count,
            "exams_count": exams_count,
            "summaries_count": summaries_count,
            "guides_count": guides_count,
            "students_count": students_count,
            "passes_count": passes_count,
            "featured_filieres": featured_filieres,
            "latest_exams": latest_exams,
            "latest_summaries": latest_summaries,
        }
        # Mise en cache courte (60 secondes) pour refléter fidèlement les ajouts réels
        cache.set(cache_key, cached_data, 60)

    context = dict(cached_data)
    return render(request, "academics/home.html", context)


def about_view(request):
    """Page À propos d'ArchivEx accessible à tous."""
    return render(request, "academics/about.html")


def student_guide_view(request):
    """Guide d'utilisation d'ArchivEx pour les étudiants."""
    return render(request, "academics/student_guide.html")


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
            Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status__in=["APPROVED", "reussi", "approved", "success"]))
        ).select_related("filiere", "semester").first()
        if active_access:
            filiere = active_access.filiere
            semester = active_access.semester
        else:
            filiere = Filiere.objects.first()

    if not semester and filiere:
        semester = Semester.objects.filter(filiere=filiere).first()

    subjects_data = []
    if semester:
        subjects = list(Subject.objects.filter(semester=semester))
        
        # Batch query for exam counts to eliminate N+1 queries
        exam_counts = dict(
            Exam.objects.filter(subject__in=subjects, is_published=True)
            .values("subject_id")
            .annotate(c=Count("id"))
            .values_list("subject_id", "c")
        )
        
        for subj in subjects:
            subjects_data.append({
                "subject": subj,
                "exams_count": exam_counts.get(subj.id, 0),
            })
        has_semester_access = can_user_access(request.user, semester)

        total_exams_count = Exam.objects.filter(semester=semester, is_published=True).count()
        premium_exams_count = Exam.objects.filter(semester=semester, is_published=True, is_free=False).count()

    context = {
        "profile": profile,
        "filiere": filiere,
        "semester": semester,
        "subjects": subjects,
        "subjects_data": subjects_data,
        "has_semester_access": has_semester_access,
        "total_exams_count": total_exams_count,
        "premium_exams_count": premium_exams_count,
    }
    return render(request, "academics/matieres.html", context)


@login_required
def semester_list_view(request, filiere_id):
    """Page listant les semestres d'une filière avec counts réels et statut d'accès."""
    filiere = get_object_or_404(Filiere.objects.select_related("school", "level"), pk=filiere_id)
    semesters = list(Semester.objects.filter(filiere=filiere).select_related("academic_year").annotate(
        subjects_num=Count("subjects")
    ))

    # Batch counts to eliminate N+1 queries
    exam_counts = dict(
        Exam.objects.filter(semester__in=semesters, is_published=True)
        .values("semester_id")
        .annotate(c=Count("id"))
        .values_list("semester_id", "c")
    )
    summary_counts = dict(
        Summary.objects.filter(subject__semester__in=semesters, publication_status="PUBLISHED")
        .values("subject__semester_id")
        .annotate(c=Count("id"))
        .values_list("subject__semester_id", "c")
    )
    guide_counts = dict(
        Guide.objects.filter(subject__semester__in=semesters, publication_status="PUBLISHED")
        .values("subject__semester_id")
        .annotate(c=Count("id"))
        .values_list("subject__semester_id", "c")
    )

    semesters_data = []
    for sem in semesters:
        semesters_data.append({
            "semester": sem,
            "has_access": can_user_access(request.user, sem),
            "subjects_num": sem.subjects_num,
            "exams_count": exam_counts.get(sem.id, 0),
            "summaries_count": summary_counts.get(sem.id, 0),
            "guides_count": guide_counts.get(sem.id, 0),
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
    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    subjects = list(Subject.objects.filter(semester=semester))

    # Batch counts to eliminate N+1 queries
    exam_counts = dict(
        Exam.objects.filter(subject__in=subjects, is_published=True)
        .values("subject_id")
        .annotate(c=Count("id"))
        .values_list("subject_id", "c")
    )
    summary_counts = dict(
        Summary.objects.filter(subject__in=subjects, publication_status="PUBLISHED")
        .values("subject_id")
        .annotate(c=Count("id"))
        .values_list("subject_id", "c")
    )
    guide_counts = dict(
        Guide.objects.filter(subject__in=subjects, publication_status="PUBLISHED")
        .values("subject_id")
        .annotate(c=Count("id"))
        .values_list("subject_id", "c")
    )

    subjects_data = []
    for subj in subjects:
        subjects_data.append({
            "subject": subj,
            "exams_count": exam_counts.get(subj.id, 0),
            "summaries_count": summary_counts.get(subj.id, 0),
            "guides_count": guide_counts.get(subj.id, 0),
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


def service_worker_view(request):
    """Sert service-worker.js avec l'en-tête Service-Worker-Allowed pour couvrir tout le domaine."""
    import os
    from django.conf import settings
    from django.http import HttpResponse, Http404

    sw_path = settings.BASE_DIR / "static" / "js" / "service-worker.js"
    if not os.path.exists(sw_path):
        sw_path = settings.BASE_DIR / "staticfiles" / "js" / "service-worker.js"
    if not os.path.exists(sw_path):
        raise Http404("Service worker non trouvé")

    with open(sw_path, "r", encoding="utf-8") as f:
        content = f.read()

    response = HttpResponse(content, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def manifest_view(request):
    """Sert manifest.json à la racine."""
    import os
    from django.conf import settings
    from django.http import HttpResponse, Http404

    manifest_path = settings.BASE_DIR / "static" / "manifest.json"
    if not os.path.exists(manifest_path):
        manifest_path = settings.BASE_DIR / "staticfiles" / "manifest.json"
    if not os.path.exists(manifest_path):
        raise Http404("Manifest non trouvé")

    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()

    response = HttpResponse(content, content_type="application/manifest+json; charset=utf-8")
    response["Cache-Control"] = "public, max-age=3600"
    return response


def icon_192_view(request):
    """Sert l'icône 192x192."""
    import os
    from django.conf import settings
    from django.http import FileResponse, Http404

    path = settings.BASE_DIR / "static" / "icons" / "icon-192.png"
    if not os.path.exists(path):
        path = settings.BASE_DIR / "staticfiles" / "icons" / "icon-192.png"
    if not os.path.exists(path):
        raise Http404("Icon non trouvée")

    response = FileResponse(open(path, "rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400"
    return response


def icon_512_view(request):
    """Sert l'icône 512x512."""
    import os
    from django.conf import settings
    from django.http import FileResponse, Http404

    path = settings.BASE_DIR / "static" / "icons" / "icon-512.png"
    if not os.path.exists(path):
        path = settings.BASE_DIR / "staticfiles" / "icons" / "icon-512.png"
    if not os.path.exists(path):
        raise Http404("Icon non trouvée")

    response = FileResponse(open(path, "rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400"
    return response


def favicon_view(request):
    """Sert l'icône favicon."""
    import os
    from django.conf import settings
    from django.http import FileResponse, Http404

    path = settings.BASE_DIR / "static" / "icons" / "icon-192.png"
    if not os.path.exists(path):
        path = settings.BASE_DIR / "staticfiles" / "icons" / "icon-192.png"
    if not os.path.exists(path):
        raise Http404("Favicon non trouvée")

    response = FileResponse(open(path, "rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400"
    return response






