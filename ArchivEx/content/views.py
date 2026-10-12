from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Summary, Guide, Article
from subscriptions.services import can_user_access


def summary_list(request):
    """Liste des résumés de cours publiés accessible publiquement (SEO)."""
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
        item.user_has_access = can_user_access(request.user, item) if request.user.is_authenticated else False

    context = {
        "summaries": summaries,
        "selected_subject": selected_subject,
        "current_school": current_school,
        "q": q or "",
    }
    return render(request, "content/summary_list.html", context)


def summary_detail(request, pk):
    """Lecture directe d'un résumé de cours avec contrôle d'accès freemium/SEO."""
    summary = get_object_or_404(
        Summary.objects.select_related(
            "subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school", "author"
        ),
        pk=pk,
        publication_status="PUBLISHED"
    )

    has_access = can_user_access(request.user, summary) if request.user.is_authenticated else bool(summary.is_free)
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


def summary_viewer_view(request, pk):
    """Page dédiée du Lecteur Académique PWA pour les fiches résumés."""
    from django.urls import reverse
    summary = get_object_or_404(
        Summary.objects.select_related(
            "subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school", "author"
        ),
        pk=pk,
        publication_status="PUBLISHED"
    )

    if not request.user.is_superuser and hasattr(request.user, "profile") and request.user.profile.filiere:
        if summary.subject and summary.subject.semester and summary.subject.semester.filiere_id:
            if summary.subject.semester.filiere_id != request.user.profile.filiere_id:
                messages.warning(
                    request,
                    f"Cette ressource appartient à la filière « {summary.subject.semester.filiere.name} ». Vous ne pouvez consulter que votre propre filière ({request.user.profile.filiere.name})."
                )
                return redirect("content:summary_list")

    has_access = can_user_access(request.user, summary) if request.user.is_authenticated else bool(summary.is_free)

    if not summary.file:
        messages.error(request, "Aucun fichier PDF n'est disponible pour ce résumé.")
        return redirect("content:summary_detail", pk=summary.pk)

    if not has_access:
        if not request.user.is_authenticated:
            messages.info(request, "Veuillez vous connecter et activer votre Pass pour consulter ce résumé.")
            return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
        messages.warning(
            request,
            "Cette ressource est réservée aux étudiants disposant du Pass actif pour ce semestre."
        )
        sem_id = summary.subject.semester_id if summary.subject and summary.subject.semester_id else 1
        return redirect("payments:pass_semestre", semester_id=sem_id)

    stream_url = reverse("content:stream_summary_pdf", kwargs={"pk": summary.id})

    if summary.subject and request.user.is_authenticated:
        from academics.models import record_ue_consultation
        record_ue_consultation(request.user, summary.subject)

    context = {
        "summary": summary,
        "resource_label": "Fiche Résumé",
        "stream_url": stream_url,
    }
    return render(request, "content/summary_viewer.html", context)


def stream_summary_pdf_view(request, pk):
    """Sert le fichier PDF dynamique du résumé tatoué/filigrané au nom de l'étudiant."""
    import os
    import logging
    from io import BytesIO
    from django.conf import settings
    from django.core.cache import cache
    from django.http import FileResponse
    from exams.services import apply_student_watermark, extract_raw_pdf_bytes
    from exams.views import _render_pdf_error_response, _sanitize_header_filename

    logger = logging.getLogger(__name__)

    summary = get_object_or_404(
        Summary.objects.select_related("subject", "subject__semester", "subject__semester__filiere"),
        pk=pk,
        publication_status="PUBLISHED"
    )

    if not request.user.is_superuser and hasattr(request.user, "profile") and request.user.profile.filiere:
        if summary.subject and summary.subject.semester and summary.subject.semester.filiere_id:
            if summary.subject.semester.filiere_id != request.user.profile.filiere_id:
                return _render_pdf_error_response("Accès non autorisé. Cette ressource appartient à une autre filière.")

    has_access = can_user_access(request.user, summary) if request.user.is_authenticated else bool(summary.is_free)
    if not has_access:
        return _render_pdf_error_response("Accès refusé. Le Pass Semestre est requis pour consulter ce résumé.")

    if not summary.file:
        return _render_pdf_error_response("Le fichier PDF de ce résumé n'est pas encore disponible sur le serveur.")

    safe_title = summary.title.replace(" ", "_")
    safe_filename = _sanitize_header_filename(f"ArchivEx_Resume_{safe_title}") + ".pdf"
    disposition = "inline"

    # Utilisateur anonyme sur ressource gratuite : servir le PDF brut, sans watermark
    if not request.user.is_authenticated:
        try:
            raw_bytes = extract_raw_pdf_bytes(summary.file)
            if raw_bytes and len(raw_bytes) > 20 and raw_bytes.startswith(b"%PDF"):
                response = FileResponse(BytesIO(raw_bytes), content_type="application/pdf")
                response["Content-Length"] = str(len(raw_bytes))
                response["Cache-Control"] = "public, max-age=86400"
                response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
                return response
            return _render_pdf_error_response("Le fichier PDF n'a pas pu être lu par le serveur.", status=404)
        except Exception:
            return _render_pdf_error_response("Le fichier PDF n'a pas pu être lu par le serveur.", status=404)

    # 1. Vérification du cache disque persistant avec watermark
    cache_dir = os.path.join(settings.MEDIA_ROOT, "cache", "watermarked_summaries")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass

    cache_disk_file = os.path.join(cache_dir, f"wm_sum_{summary.id}_{request.user.id}.pdf")
    if os.path.exists(cache_disk_file) and os.path.getsize(cache_disk_file) > 100:
        try:
            with open(cache_disk_file, "rb") as test_f:
                header = test_f.read(8)
            if header.startswith(b"%PDF"):
                response = FileResponse(open(cache_disk_file, "rb"), content_type="application/pdf")
                response["Content-Length"] = str(os.path.getsize(cache_disk_file))
                response["Cache-Control"] = "private, no-transform, max-age=86400"
                response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
                return response
            else:
                try:
                    os.remove(cache_disk_file)
                except Exception:
                    pass
        except Exception:
            pass

    cache_key = f"wm_sum_pdf_{summary.id}_{request.user.id}"
    cached_pdf = cache.get(cache_key)
    if cached_pdf and isinstance(cached_pdf, bytes) and cached_pdf.startswith(b"%PDF"):
        try:
            tmp_disk_file = f"{cache_disk_file}.tmp.{os.getpid()}"
            with open(tmp_disk_file, "wb") as f:
                f.write(cached_pdf)
            os.replace(tmp_disk_file, cache_disk_file)
        except Exception:
            pass
        response = FileResponse(BytesIO(cached_pdf), content_type="application/pdf")
        response["Content-Length"] = str(len(cached_pdf))
        response["Cache-Control"] = "private, no-transform, max-age=86400"
        response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
        return response

    try:
        watermarked_io = apply_student_watermark(summary.file, request.user)
        pdf_bytes = watermarked_io.getvalue()
        cache.set(cache_key, pdf_bytes, timeout=10800)
        try:
            tmp_disk_file = f"{cache_disk_file}.tmp.{os.getpid()}"
            with open(tmp_disk_file, "wb") as f:
                f.write(pdf_bytes)
            os.replace(tmp_disk_file, cache_disk_file)
        except Exception:
            pass

        response = FileResponse(BytesIO(pdf_bytes), content_type="application/pdf")
        response["Content-Length"] = str(len(pdf_bytes))
        response["Cache-Control"] = "private, no-transform, max-age=86400"
        response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
        return response
    except Exception as e:
        logger.warning(f"Erreur application watermark PDF pour résumé {summary.id}: {e}")
        try:
            raw_bytes = extract_raw_pdf_bytes(summary.file)
            if raw_bytes and len(raw_bytes) > 20 and raw_bytes.startswith(b"%PDF"):
                response = FileResponse(BytesIO(raw_bytes), content_type="application/pdf")
                response["Content-Length"] = str(len(raw_bytes))
                response["Cache-Control"] = "private, no-transform, max-age=86400"
                response["Content-Disposition"] = f'{disposition}; filename="{safe_filename}"'
                return response
            return _render_pdf_error_response("Le fichier PDF n'a pas pu être lu par le serveur.", status=404)
        except Exception:
            return _render_pdf_error_response("Le fichier PDF n'a pas pu être lu par le serveur.", status=404)


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
