from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Summary, Guide, Article
from subscriptions.services import can_user_access


@login_required
def summary_list(request):
    """Liste des résumés de cours publiés."""
    summaries = Summary.objects.filter(publication_status="PUBLISHED").select_related(
        "subject", "subject__semester", "subject__semester__filiere", "author"
    )

    subject_id = request.GET.get("subject")
    if subject_id:
        summaries = summaries.filter(subject_id=subject_id)

    q = request.GET.get("q")
    if q:
        summaries = summaries.filter(Q(title__icontains=q) | Q(introduction__icontains=q))

    for item in summaries:
        item.user_has_access = can_user_access(request.user, item)

    context = {
        "summaries": summaries,
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

    context = {
        "summary": summary,
        "has_access": has_access,
    }
    return render(request, "content/summary_detail.html", context)


@login_required
def guide_list(request):
    """Liste des guides de matières."""
    guides = Guide.objects.filter(publication_status="PUBLISHED").select_related(
        "subject", "subject__semester", "subject__semester__filiere", "author"
    )

    subject_id = request.GET.get("subject")
    if subject_id:
        guides = guides.filter(subject_id=subject_id)

    for guide in guides:
        guide.user_has_access = can_user_access(request.user, guide)

    context = {
        "guides": guides,
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

    context = {
        "guide": guide,
        "has_access": has_access,
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


def article_detail(request, pk):
    """Lecture d'un conseil ou article pédagogique."""
    article = get_object_or_404(
        Article.objects.select_related("target_school", "target_filiere", "author"),
        pk=pk,
        publication_status="PUBLISHED"
    )

    context = {
        "article": article,
    }
    return render(request, "content/article_detail.html", context)
