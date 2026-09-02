import os
import unicodedata
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, FileResponse, Http404, JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.contrib import messages
from django.db.models import Q

from .models import Exam
from accounts.models import Favorite
from payments.models import SemesterAccess
from academics.models import Subject


from subscriptions.services import (
    can_user_access,
    can_user_access_exam_pdf,
    can_user_access_correction,
    can_user_access_summary,
)


@login_required
def exam_list(request):
    """Vue des épreuves d'une UE ou de recherche d'épreuves (Connexion requise)."""
    mode = request.GET.get("mode", "premium")  # 'free' or 'premium'
    if request.resolver_match and request.resolver_match.url_name == "free_liste":
        mode = "free"

    exams = Exam.objects.filter(is_published=True).select_related(
        "subject", "filiere", "level", "academic_year", "semester", "filiere__school", "summary"
    ).order_by("-created_at")

    if mode == "free":
        exams = exams.filter(is_free=True)

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
        exam.user_has_access = can_user_access_exam_pdf(request.user, exam)
        exam.user_has_correction_access = can_user_access_correction(request.user, exam)
        exam.user_has_summary_access = can_user_access_summary(request.user, exam)
        exam.is_favorited = exam.id in user_favorites

    context = {
        "page_obj": page_obj,
        "exams": page_obj,
        "selected_subject": selected_subject,
        "q": q or "",
        "selected_type": exam_type or "",
        "selected_year": year or "",
        "exam_types": Exam.EXAM_TYPE_CHOICES,
        "mode": mode,
        "is_free_mode": mode == "free",
    }
    return render(request, "exams/liste.html", context)


@login_required
def exam_detail(request, pk):
    """Page de détail d'une épreuve (Connexion requise)."""
    exam = get_object_or_404(
        Exam.objects.select_related(
            "subject", "semester", "filiere", "level", "academic_year", "filiere__school", "summary"
        ),
        pk=pk,
        is_published=True
    )

    has_access = can_user_access_exam_pdf(request.user, exam)
    has_correction_access = can_user_access_correction(request.user, exam)
    has_summary_access = can_user_access_summary(request.user, exam)
    is_favorited = Favorite.objects.filter(user=request.user, exam=exam).exists()

    exams_count = 0
    summaries_count = 0
    guides_count = 0
    if not has_access and exam.semester:
        from content.models import Summary, Guide
        sem = exam.semester
        exams_count = Exam.objects.filter(semester=sem, is_published=True).count()
        summaries_count = Summary.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()
        guides_count = Guide.objects.filter(subject__semester=sem, publication_status="PUBLISHED").count()

    context = {
        "exam": exam,
        "has_access": has_access,
        "has_correction_access": has_correction_access,
        "has_summary_access": has_summary_access,
        "is_favorited": is_favorited,
        "exams_count": exams_count,
        "summaries_count": summaries_count,
        "guides_count": guides_count,
    }
    return render(request, "exams/detail.html", context)


def _sanitize_header_filename(name):
    """Convertit tout nom de fichier en ASCII pur sans accents ni caractères spéciaux pour les en-têtes HTTP."""
    if not name:
        return "document.pdf"
    normalized = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('utf-8')
    clean = "".join(c if c.isalnum() or c in "._-" else "_" for c in normalized)
    return clean or "document.pdf"


def _get_safe_file_path(field_file):
    """Retourne le chemin système du fichier ou son objet s'il existe."""
    if not field_file or not bool(field_file):
        return None
    try:
        path = field_file.path
        if os.path.exists(path):
            return path
    except Exception:
        pass
    try:
        if hasattr(field_file, "url") and field_file.url:
            return field_file
    except Exception:
        pass
    return None


@login_required
def stream_exam_pdf(request, pk):
    """Vue de sécurité : Sert le fichier PDF de l'épreuve principale."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)

    has_access = can_user_access_exam_pdf(request.user, exam)

    if not has_access:
        messages.warning(
            request,
            "Cette épreuve est réservée aux étudiants disposant du Pass actif pour ce semestre."
        )
        sem_id = exam.semester.id if exam.semester else (exam.subject.semester.id if exam.subject and exam.subject.semester else 1)
        return redirect("payments:pass_semestre", semester_id=sem_id)

    file_obj = _get_safe_file_path(exam.file)
    if not file_obj:
        messages.error(request, "Le fichier de cette épreuve n'est pas encore disponible sur le serveur.")
        return redirect("exams:detail", pk=exam.pk)

    if isinstance(file_obj, str):
        response = FileResponse(open(file_obj, "rb"), content_type="application/pdf")
    else:
        return redirect(file_obj.url)

    is_download = request.GET.get("download") == "1"
    disposition = "attachment" if is_download else "inline"
    subj_name = exam.subject.name if exam.subject else "Epreuve"
    safe_filename = _sanitize_header_filename(f"ArchivEx_{subj_name}_{exam.year}") + ".pdf"
    response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
    return response


@login_required
def stream_correction_pdf(request, pk):
    """Vue de sécurité : Sert le fichier PDF de la correction (Accès Premium strict)."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)

    if not exam.correction_file:
        messages.error(request, "Aucune correction PDF n'est associée à cette épreuve.")
        return redirect("exams:detail", pk=exam.pk)

    has_access = can_user_access_correction(request.user, exam)
    if not has_access:
        messages.warning(
            request,
            "Les corrections sont des ressources Premium réservées aux étudiants disposant du Pass actif pour ce semestre."
        )
        sem_id = exam.semester.id if exam.semester else (exam.subject.semester.id if exam.subject and exam.subject.semester else 1)
        return redirect("payments:pass_semestre", semester_id=sem_id)

    file_obj = _get_safe_file_path(exam.correction_file)
    if not file_obj:
        messages.error(request, "Le fichier de correction n'est pas encore disponible sur le serveur.")
        return redirect("exams:detail", pk=exam.pk)

    if isinstance(file_obj, str):
        response = FileResponse(open(file_obj, "rb"), content_type="application/pdf")
    else:
        return redirect(file_obj.url)

    is_download = request.GET.get("download") == "1"
    disposition = "attachment" if is_download else "inline"
    subj_name = exam.subject.name if exam.subject else "Correction"
    safe_filename = _sanitize_header_filename(f"ArchivEx_Correction_{subj_name}_{exam.year}") + ".pdf"
    response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
    return response


@login_required
def stream_summary_pdf(request, pk):
    """Vue de sécurité : Sert le fichier PDF du résumé de cours (Accès Premium strict)."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)

    target_file = None
    if exam.summary_file:
        target_file = exam.summary_file
    elif exam.summary and exam.summary.file:
        target_file = exam.summary.file

    if not target_file:
        messages.error(request, "Aucun résumé PDF n'est associé à cette épreuve.")
        return redirect("exams:detail", pk=exam.pk)

    has_access = can_user_access_summary(request.user, exam)
    if not has_access:
        messages.warning(
            request,
            "Les résumés de cours sont des ressources Premium réservées aux étudiants disposant du Pass actif pour ce semestre."
        )
        sem_id = exam.semester.id if exam.semester else (exam.subject.semester.id if exam.subject and exam.subject.semester else 1)
        return redirect("payments:pass_semestre", semester_id=sem_id)

    file_obj = _get_safe_file_path(target_file)
    if not file_obj:
        messages.error(request, "Le fichier du résumé n'est pas encore disponible sur le serveur.")
        return redirect("exams:detail", pk=exam.pk)

    if isinstance(file_obj, str):
        response = FileResponse(open(file_obj, "rb"), content_type="application/pdf")
    else:
        return redirect(file_obj.url)

    is_download = request.GET.get("download") == "1"
    disposition = "attachment" if is_download else "inline"
    subj_name = exam.subject.name if exam.subject else "Resume"
    safe_filename = _sanitize_header_filename(f"ArchivEx_Resume_{subj_name}_{exam.year}") + ".pdf"
    response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
    return response


@login_required
def toggle_favorite(request, pk):
    """Ajoute ou retire une épreuve des favoris de l'utilisateur."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)
    favorite, created = Favorite.objects.get_or_create(user=request.user, exam=exam)

    if not created:
        favorite.delete()
        messages.info(request, f"« {exam.title} » a été retirée de vos favoris.")
    else:
        messages.success(request, f"« {exam.title} » a été ajoutée à vos favoris.")

    return redirect("exams:detail", pk=exam.pk)


def _render_pdf_error_response(message="Ce fichier PDF n'est pas encore disponible sur le serveur."):
    """Retourne une réponse HTML propre à afficher à l'intérieur du lecteur PDF / Iframe sans erreur 500 ni boucle."""
    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
                background-color: #071a49;
                color: #f8fafc;
                text-align: center;
            }}
            .card {{
                max-width: 420px;
                padding: 32px;
                background: #0f2766;
                border: 1px solid #1e40af;
                border-radius: 24px;
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
            }}
            .icon {{
                font-size: 32px;
                margin-bottom: 12px;
            }}
            h3 {{
                margin: 0 0 8px;
                font-size: 16px;
                font-weight: 800;
                color: #fbbf24;
            }}
            p {{
                margin: 0;
                font-size: 13px;
                line-height: 1.5;
                color: #93c5fd;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon">⚠️</div>
            <h3>Document Indisponible</h3>
            <p>{message}</p>
        </div>
    </body>
    </html>
    """
    return HttpResponse(html_content, content_type="text/html", status=200)


@login_required
def student_viewer_view(request, pk):
    """Page dédiée du Lecteur Académique (Viewer sécurisé avec iframe et anti-copie)."""
    exam = get_object_or_404(Exam, pk=pk, is_published=True)
    res_type = request.GET.get("type", "exam")

    resource_label = "Épreuve d'Examen"
    if res_type == "correction":
        has_access = can_user_access_correction(request.user, exam)
        resource_label = "Correction Détaillée"
        corr_target = exam.correction_file
        if not bool(corr_target) and exam.cloud_correction_file:
            corr_target = exam.cloud_correction_file.file
        if not _get_safe_file_path(corr_target):
            messages.error(request, "Aucune correction n'est actuellement disponible pour cette épreuve.")
            return redirect("exams:detail", pk=exam.pk)

    elif res_type == "summary":
        has_access = can_user_access_summary(request.user, exam)
        resource_label = "Fiche Résumé"
        summary_target = exam.summary_file or (exam.summary.file if exam.summary else None)
        if not bool(summary_target) and exam.cloud_summary_file:
            summary_target = exam.cloud_summary_file.file
        if not _get_safe_file_path(summary_target):
            messages.error(request, "Aucun résumé n'est actuellement disponible pour cette épreuve.")
            return redirect("exams:detail", pk=exam.pk)

    else:
        has_access = can_user_access_exam_pdf(request.user, exam)
        exam_target = exam.file
        if not bool(exam_target) and exam.cloud_file:
            exam_target = exam.cloud_file.file
        if not _get_safe_file_path(exam_target):
            messages.error(request, "Le fichier PDF de cette épreuve est en cours d'importation.")
            return redirect("exams:detail", pk=exam.pk)

    if not has_access:
        messages.warning(
            request,
            "Cette ressource est réservée aux étudiants disposant du Pass actif pour ce semestre."
        )
        sem_id = exam.semester.id if exam.semester else (exam.subject.semester.id if exam.subject and exam.subject.semester else 1)
        return redirect("payments:pass_semestre", semester_id=sem_id)

    stream_url = reverse("exams:stream_watermarked_pdf", kwargs={"pk": exam.id}) + f"?type={res_type}"

    context = {
        "exam": exam,
        "resource_label": resource_label,
        "res_type": res_type,
        "stream_url": stream_url,
    }
    return render(request, "exams/viewer.html", context)


@login_required
def stream_watermarked_pdf_view(request, pk):
    """Sert le fichier PDF dynamique tatoué/filigrané au nom et horodatage de l'étudiant."""
    from .services import apply_student_watermark

    exam = get_object_or_404(Exam, pk=pk, is_published=True)
    res_type = request.GET.get("type", "exam")

    target_file = None
    has_access = False

    if res_type == "correction":
        target_file = exam.correction_file
        if not bool(target_file) and exam.cloud_correction_file:
            target_file = exam.cloud_correction_file.file
        has_access = can_user_access_correction(request.user, exam)

    elif res_type == "summary":
        target_file = exam.summary_file or (exam.summary.file if exam.summary else None)
        if not bool(target_file) and exam.cloud_summary_file:
            target_file = exam.cloud_summary_file.file
        has_access = can_user_access_summary(request.user, exam)

    else:
        target_file = exam.file
        if not bool(target_file) and exam.cloud_file:
            target_file = exam.cloud_file.file
        has_access = can_user_access_exam_pdf(request.user, exam)

    if not has_access:
        return _render_pdf_error_response("Accès refusé. Le Pass Semestre est requis pour consulter ce document.")

    file_obj = _get_safe_file_path(target_file)
    if not file_obj:
        return _render_pdf_error_response("Le fichier PDF demandé n'est pas encore disponible sur le serveur.")

    try:
        watermarked_io = apply_student_watermark(file_obj, request.user)
        response = FileResponse(
            watermarked_io,
            content_type="application/pdf"
        )
        subj_name = exam.subject.name if exam.subject else "Document"
        safe_filename = _sanitize_header_filename(f"ArchivEx_{res_type}_{subj_name}_{exam.year}") + ".pdf"
        response["Content-Disposition"] = f'inline; filename="{safe_filename}"'
        return response
    except Exception:
        try:
            if isinstance(file_obj, str) and os.path.exists(file_obj):
                watermarked_io = open(file_obj, "rb")
            elif hasattr(file_obj, "open"):
                watermarked_io = file_obj.open("rb")
            else:
                return redirect(getattr(file_obj, "url", "/"))
            
            response = FileResponse(
                watermarked_io,
                content_type="application/pdf"
            )
            subj_name = exam.subject.name if exam.subject else "Document"
            safe_filename = _sanitize_header_filename(f"ArchivEx_{res_type}_{subj_name}_{exam.year}") + ".pdf"
            response["Content-Disposition"] = f'inline; filename="{safe_filename}"'
            return response
        except Exception:
            return _render_pdf_error_response("Le fichier PDF n'a pas pu être lu par le serveur.")