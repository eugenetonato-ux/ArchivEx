from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Summary, Guide, Article
from subscriptions.services import can_user_access


@login_required
def summary_list(request):
    """Liste des résumés de cours publiés."""
    from academics.models import Subject

    summaries = Summary.objects.filter(publication_status="PUBLISHED").select_related(
        "subject", "subject__semester", "subject__semester__filiere", "author"
    )

    subject_id = request.GET.get("subject")
    selected_subject = None
    if subject_id:
        selected_subject = Subject.objects.filter(pk=subject_id).first()
        if selected_subject:
            summaries = summaries.filter(subject=selected_subject)

    q = request.GET.get("q")
    if q:
        summaries = summaries.filter(Q(title__icontains=q) | Q(introduction__icontains=q))

    for item in summaries:
        item.user_has_access = can_user_access(request.user, item)

    context = {
        "summaries": summaries,
        "selected_subject": selected_subject,
        "q": q or "",
    }
    return render(request, "content/summary_list.html", context)


@login_required
def summary_detail(request, pk):
    """Lecture directe d'un résumé de cours avec contrôle d'accès."""
    summary = get_object_or_404(
        Summary.objects.select_related(
            "subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school", "author"
        ),
        pk=pk,
        publication_status="PUBLISHED"
    )

    has_access = can_user_access(request.user, summary)

    exams_count = 0
    summaries_count = 0
    guides_count = 0
    if not has_access and summary.subject and summary.subject.semester:
        from exams.models import Exam
        sem = summary.subject.semester
        exams_count = Exam.objects.filter(semester=sem, is_published=True).count()
        summaries_count = Summary.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()
        guides_count = Guide.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()

    context = {
        "summary": summary,
        "has_access": has_access,
        "exams_count": exams_count,
        "summaries_count": summaries_count,
        "guides_count": guides_count,
    }
    return render(request, "content/summary_detail.html", context)


@login_required
def guide_list(request):
    """Liste des guides de matières."""
    from academics.models import Subject

    guides = Guide.objects.filter(publication_status="PUBLISHED").select_related(
        "subject", "subject__semester", "subject__semester__filiere", "author"
    )

    subject_id = request.GET.get("subject")
    selected_subject = None
    if subject_id:
        selected_subject = Subject.objects.filter(pk=subject_id).first()
        if selected_subject:
            guides = guides.filter(subject=selected_subject)

    for guide in guides:
        guide.user_has_access = can_user_access(request.user, guide)

    context = {
        "guides": guides,
        "selected_subject": selected_subject,
    }
    return render(request, "content/guide_list.html", context)



@login_required
def guide_detail(request, pk):
    """Affichage complet d'un guide méthodologique de matière."""
    guide = get_object_or_404(
        Guide.objects.select_related(
            "subject", "subject__semester", "subject__semester__filiere", "author"
        ),
        pk=pk,
        publication_status="PUBLISHED"
    )

    has_access = can_user_access(request.user, guide)

    exams_count = 0
    summaries_count = 0
    guides_count = 0
    if not has_access and guide.subject and guide.subject.semester:
        from exams.models import Exam
        sem = guide.subject.semester
        exams_count = Exam.objects.filter(semester=sem, is_published=True).count()
        summaries_count = Summary.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()
        guides_count = Guide.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()

    context = {
        "guide": guide,
        "has_access": has_access,
        "exams_count": exams_count,
        "summaries_count": summaries_count,
        "guides_count": guides_count,
    }
    return render(request, "content/guide_detail.html", context)



def article_list(request):
    """Liste des conseils pédagogiques et articles."""
    articles = Article.objects.filter(publication_status="PUBLISHED").select_related(
        "target_school", "target_filiere", "author"
    )

    category = request.GET.get("category")
    if category:
        articles = articles.filter(category=category)

    context = {
        "articles": articles,
        "selected_category": category or "",
        "categories": Article.CATEGORY_CHOICES,
    }
    return render(request, "content/article_list.html", context)


def student_guide_view(request):
    """
    Landing Page du Guide Étudiant & Centre de Connaissances ArchivEx.
    Organise la méthodologie universitaire, les conseils de révision,
    l'exploitation des épreuves et le fonctionnement du Pass.
    """
    articles = Article.objects.filter(publication_status="PUBLISHED").select_related(
        "target_school", "target_filiere", "author"
    )

    profile = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    if profile and profile.school:
        targeted_articles = articles.filter(
            Q(target_school=profile.school) | Q(target_school__isnull=True)
        )
    else:
        targeted_articles = articles

    methodology_articles = targeted_articles.filter(category="METHODOLOGY")
    exam_prep_articles = targeted_articles.filter(category="EXAM_PREP")
    general_articles = targeted_articles.filter(category="GENERAL")
    orientation_articles = targeted_articles.filter(category="ORIENTATION")

    context = {
        "articles": targeted_articles,
        "methodology_articles": methodology_articles,
        "exam_prep_articles": exam_prep_articles,
        "general_articles": general_articles,
        "orientation_articles": orientation_articles,
        "profile": profile,
    }
    return render(request, "content/student_guide.html", context)


def article_detail(request, pk):
    """Lecture complète d'un article ou conseil pédagogique."""
    article = get_object_or_404(
        Article.objects.select_related("target_school", "target_filiere", "author"),
        pk=pk,
        publication_status="PUBLISHED"
    )

    context = {
        "article": article,
    }
    return render(request, "content/article_detail.html", context)
