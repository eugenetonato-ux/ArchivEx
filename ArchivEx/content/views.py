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
    from academics.context import get_current_school
    current_school = get_current_school(request)

    summaries = Summary.objects.filter(publication_status="PUBLISHED").select_related(
        "subject", "subject__semester", "subject__semester__filiere", "author"
    )
    if current_school:
        summaries = summaries.filter(subject__semester__filiere__school=current_school)

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
        "current_school": current_school,
        "q": q or "",
    }
    return render(request, "content/summary_list.html", context)


def summary_detail(request, pk):
    """Lecture directe d'un résumé de cours avec contrôle d'accès."""
    if not request.user.is_authenticated:
        from django.urls import reverse
        messages.info(request, "Connectez-vous pour consulter ce résumé de cours.")
        return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")

    summary = get_object_or_404(
        Summary.objects.select_related(
            "subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school", "author"
        ),
        pk=pk,
        publication_status="PUBLISHED"
    )

    has_access = can_user_access(request.user, summary)
    if summary.subject and request.user.is_authenticated:
        from academics.models import record_ue_consultation
        record_ue_consultation(request.user, summary.subject)

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
    """Les guides ont été retirés de la plateforme (ressources : épreuves, corrigés, résumés)."""
    return redirect("content:summary_list")


@login_required
def guide_detail(request, pk):
    """Les guides ont été retirés de la plateforme."""
    return redirect("content:summary_list")



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
    """Les guides ont été retirés de la plateforme (ressources : épreuves, corrigés, résumés)."""
    return redirect("academics:home")


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
