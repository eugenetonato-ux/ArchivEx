import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, FileResponse, Http404, JsonResponse
from django.core.paginator import Paginator
from django.contrib import messages
from django.db.models import Q

from .models import Exam
from accounts.models import Favorite
from payments.models import SemesterAccess
from academics.models import Subject


from subscriptions.services import can_user_access


@login_required
def exam_list(request):
    """Vue des épreuves d'une UE ou de recherche d'épreuves (Connexion requise)."""
    exams = Exam.objects.filter(is_published=True).select_related(
        "subject", "filiere", "level", "academic_year", "semester", "filiere__school"
    ).order_by("-created_at")

    # Search query
    q = request.GET.get("q")
    if q:
        exams = exams.filter(
            Q(title__icontains=q) |
            Q(subject__name__icontains=q) |
            Q(description__icontains=q)
        )

    # Filter by exam type
    exam_type = request.GET.get("type")
    if exam_type:
        exams = exams.filter(exam_type=exam_type)

    # Filter by year
    year = request.GET.get("year")
    if year:
        exams = exams.filter(year=year)

    # Filter by subject (UE)
    subject_id = request.GET.get("subject")
    selected_subject = None
    if subject_id:
        selected_subject = Subject.objects.filter(pk=subject_id).select_related(
            "semester", "semester__filiere", "semester__filiere__school", "semester__filiere__level"
        ).first()
        if selected_subject:
            exams = exams.filter(subject=selected_subject)

    # Filter by semester
    semester_id = request.GET.get("semester")
    if semester_id:
        exams = exams.filter(semester_id=semester_id)

    # Filter by filiere
    filiere_id = request.GET.get("filiere")
    if filiere_id:
        exams = exams.filter(filiere_id=filiere_id)

    # Pagination
    paginator = Paginator(exams, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    user_favorites = set(
        Favorite.objects.filter(user=request.user).values_list("exam_id", flat=True)
    )

    for exam in page_obj:
        exam.user_has_access = can_user_access(request.user, exam)
        exam.is_favorited = exam.id in user_favorites

    context = {
        "page_obj": page_obj,
        "exams": page_obj,
        "selected_subject": selected_subject,
        "q": q or "",
        "selected_type": exam_type or "",
        "selected_year": year or "",
        "exam_types": Exam.EXAM_TYPE_CHOICES,
    }
    return render(request, "exams/liste.html", context)


@login_required
def exam_detail(request, pk):
    """Page de détail d'une épreuve (Connexion requise)."""
    exam = get_object_or_404(
        Exam.objects.select_related(
            "subject", "semester", "filiere", "level", "academic_year", "filiere__school"
        ),
        pk=pk,
        is_published=True
    )

    has_access = can_user_access(request.user, exam)
    is_favorited = Favorite.objects.filter(user=request.user, exam=exam).exists()

    context = {
        "exam": exam,
        "has_access": has_access,
        "is_favorited": is_favorited,
    }
    return render(request, "exams/detail.html", context)


@login_required
def stream_exam_pdf(request, pk):
    """Vue de sécurité : Sert le fichier PDF de l'épreuve (Connexion requise)."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)

    has_access = can_user_access(request.user, exam)

    if not has_access:
        messages.warning(
            request,
            "Cette épreuve est réservée aux étudiants disposant du Pass actif pour ce semestre."
        )
        return redirect("payments:pass_semestre", semester_id=exam.semester.id)


    if not exam.file or not os.path.exists(exam.file.path):
        raise Http404("Le fichier de l'épreuve est introuvable sur le serveur.")

    response = FileResponse(
        open(exam.file.path, "rb"),
        content_type="application/pdf"
    )
    is_download = request.GET.get("download") == "1"
    disposition = "attachment" if is_download else "inline"
    safe_filename = f"ArchivEx_{exam.subject.name}_{exam.year}.pdf".replace(" ", "_")
    response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
    return response


@login_required
def toggle_favorite(request, pk):
    """Ajoute ou retire une épreuve des favoris de l'utilisateur."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)
    favorite, created = Favorite.objects.get_or_create(user=request.user, exam=exam)

    if not created:
        favorite.delete()
        is_favorited = False
        messages.info(request, f"« {exam.title} » retiré de tes favoris.")
    else:
        is_favorited = True
        messages.success(request, f"« {exam.title} » ajouté à tes favoris ❤")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok", "is_favorited": is_favorited})

    next_url = request.META.get("HTTP_REFERER") or "exams:detail"
    return redirect(next_url if next_url != request.build_absolute_uri() else "exams:liste")