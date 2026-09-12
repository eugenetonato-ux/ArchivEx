import os
import re
import unicodedata
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, FileResponse, Http404, JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from .models import Exam
from accounts.models import Favorite
from payments.models import SemesterAccess
from academics.models import Subject, Filiere, Semester, AcademicYear


from subscriptions.services import (
    can_user_access,
    can_user_access_exam_pdf,
    can_user_access_correction,
    can_user_access_summary,
    has_user_valid_pass,
)


def parse_sort_year(academic_year=None, exam_year=None, date_val=None):
    """Extrait une année entière numérique pour garantir le tri strict de la plus récente à la plus ancienne."""
    if academic_year and getattr(academic_year, "label", None):
        m = re.search(r"(\d{4})", str(academic_year.label))
        if m:
            return int(m.group(1))
    if exam_year:
        try:
            return int(exam_year)
        except (ValueError, TypeError):
            pass
    if date_val:
        return date_val.year
    return 0


def format_academic_year(academic_year=None, exam_year=None, date_val=None):
    """Formate l'affichage de l'année académique de manière sobre et naturelle (ex: 2024–2025)."""
    if academic_year and getattr(academic_year, "label", None):
        return str(academic_year.label).replace("-", "–")
    if exam_year:
        try:
            y = int(exam_year)
            if y > 2000:
                return f"{y - 1}–{y}"
            return str(y)
        except (ValueError, TypeError):
            return str(exam_year)
    if date_val:
        y = date_val.year
        return f"{y - 1}–{y}"
    return "Année récente"


def resources_view(request, mode=None):
    """
    Espace central 'Ressources' d'ArchivEx :
    - 2 modes principaux : 'free' (Ressources gratuites) ou 'premium' (Ressources premium)
    - 3 catégories par mode : 'epreuves', 'corrections', 'resumes'
    - Regroupement systématique par UE / Matière, puis par années disponibles (triées de la plus récente à la plus ancienne).
    """
    mode = mode or request.GET.get("mode")
    if request.resolver_match and request.resolver_match.url_name == "free_liste":
        mode = "free"
    elif request.resolver_match and request.resolver_match.url_name == "premium_liste":
        mode = "premium"
    elif not mode:
        mode = "premium"

    category = request.GET.get("category", "epreuves").strip().lower()
    if category not in ("epreuves", "corrections", "resumes"):
        category = "epreuves"

    # Paramètres de recherche et filtrage multi-critères
    q = request.GET.get("q", "").strip()
    selected_subject_id = request.GET.get("subject", "").strip()
    selected_filiere_id = request.GET.get("filiere", "").strip()
    selected_semester_id = request.GET.get("semester", "").strip()
    selected_year = request.GET.get("year", "").strip()
    selected_type = request.GET.get("exam_type", "").strip()

    subjects_map = {}

    if category == "epreuves":
        exams = Exam.objects.filter(is_published=True).select_related(
            "subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school", "academic_year"
        ).filter(
            (Q(file__isnull=False) & ~Q(file="")) | Q(cloud_file__isnull=False)
        )
        if mode == "free":
            exams = exams.filter(Q(is_free=True) | Q(subject__is_free=True))

        if q:
            exams = exams.filter(
                Q(subject__name__icontains=q) |
                Q(subject__code__icontains=q) |
                Q(title__icontains=q) |
                Q(subject__semester__filiere__name__icontains=q) |
                Q(subject__semester__label__icontains=q) |
                Q(academic_year__label__icontains=q)
            )
        if selected_subject_id:
            exams = exams.filter(subject_id=selected_subject_id)
        if selected_filiere_id:
            exams = exams.filter(subject__semester__filiere_id=selected_filiere_id)
        if selected_semester_id:
            exams = exams.filter(subject__semester_id=selected_semester_id)
        if selected_year:
            exams = exams.filter(Q(academic_year__label__icontains=selected_year) | Q(academic_year_id=selected_year) | Q(year__icontains=selected_year))
        if selected_type:
            exams = exams.filter(exam_type=selected_type)

        for exam in exams:
            subj = exam.subject
            if not subj:
                continue
            if subj.id not in subjects_map:
                subjects_map[subj.id] = {
                    "subject": subj,
                    "years": [],
                    "seen_keys": set(),
                }

            year_label = format_academic_year(exam.academic_year, exam.year)
            sort_year = parse_sort_year(exam.academic_year, exam.year)

            session_label = exam.get_exam_type_display() or "Examen"
            unique_key = f"{year_label}_{session_label}_{exam.id}"
            if unique_key in subjects_map[subj.id]["seen_keys"]:
                continue
            subjects_map[subj.id]["seen_keys"].add(unique_key)

            is_locked = False
            if mode == "premium":
                is_locked = not can_user_access_exam_pdf(request.user, exam)

            viewer_url = reverse("exams:student_viewer", kwargs={"pk": exam.id}) + "?type=exam"
            subjects_map[subj.id]["years"].append({
                "year_label": year_label,
                "sort_year": sort_year,
                "title": exam.title,
                "session": session_label,
                "exam_id": exam.id,
                "is_locked": is_locked,
                "viewer_url": viewer_url,
                "exam": exam,
            })

    elif category == "corrections":
        exams = Exam.objects.filter(is_published=True).select_related(
            "subject", "subject__semester", "subject__semester__filiere", "subject__semester__filiere__school", "academic_year"
        ).filter(
            (Q(correction_file__isnull=False) & ~Q(correction_file="")) | Q(cloud_correction_file__isnull=False)
        )
        if mode == "free":
            exams = exams.filter(Q(is_free_correction=True) | Q(subject__is_free_correction=True))

        if q:
            exams = exams.filter(
                Q(subject__name__icontains=q) |
                Q(subject__code__icontains=q) |
                Q(title__icontains=q) |
                Q(subject__semester__filiere__name__icontains=q) |
                Q(subject__semester__label__icontains=q) |
                Q(academic_year__label__icontains=q)
            )
        if selected_subject_id:
            exams = exams.filter(subject_id=selected_subject_id)
        if selected_filiere_id:
            exams = exams.filter(subject__semester__filiere_id=selected_filiere_id)
        if selected_semester_id:
            exams = exams.filter(subject__semester_id=selected_semester_id)
        if selected_year:
            exams = exams.filter(Q(academic_year__label__icontains=selected_year) | Q(academic_year_id=selected_year) | Q(year__icontains=selected_year))
        if selected_type:
            exams = exams.filter(exam_type=selected_type)

        for exam in exams:
            subj = exam.subject
            if not subj:
                continue
            if subj.id not in subjects_map:
                subjects_map[subj.id] = {
                    "subject": subj,
                    "years": [],
                    "seen_keys": set(),
                }

            year_label = format_academic_year(exam.academic_year, exam.year)
            sort_year = parse_sort_year(exam.academic_year, exam.year)

            session_label = exam.get_exam_type_display() or "Correction"
            unique_key = f"{year_label}_{session_label}_{exam.id}"
            if unique_key in subjects_map[subj.id]["seen_keys"]:
                continue
            subjects_map[subj.id]["seen_keys"].add(unique_key)

            is_locked = False
            if mode == "premium":
                is_locked = not can_user_access_correction(request.user, exam)

            viewer_url = reverse("exams:student_viewer", kwargs={"pk": exam.id}) + "?type=correction"
            subjects_map[subj.id]["years"].append({
                "year_label": year_label,
                "sort_year": sort_year,
                "title": f"Correction — {exam.title}",
                "session": f"{session_label} corrigée",
                "exam_id": exam.id,
                "is_locked": is_locked,
                "viewer_url": viewer_url,
                "exam": exam,
            })

    elif category == "resumes":
        from content.models import Summary as CourseSummary

        # A. Fiches résumés issues des épreuves
        exam_summaries = Exam.objects.filter(is_published=True).select_related(
            "subject", "subject__semester", "subject__semester__filiere", "academic_year"
        ).filter(
            (Q(summary_file__isnull=False) & ~Q(summary_file="")) | Q(cloud_summary_file__isnull=False)
        )
        if mode == "free":
            exam_summaries = exam_summaries.filter(Q(is_free_correction=True) | Q(subject__is_free_correction=True))

        if q:
            exam_summaries = exam_summaries.filter(
                Q(subject__name__icontains=q) |
                Q(subject__code__icontains=q) |
                Q(title__icontains=q) |
                Q(subject__semester__filiere__name__icontains=q) |
                Q(subject__semester__label__icontains=q) |
                Q(academic_year__label__icontains=q)
            )
        if selected_subject_id:
            exam_summaries = exam_summaries.filter(subject_id=selected_subject_id)
        if selected_filiere_id:
            exam_summaries = exam_summaries.filter(subject__semester__filiere_id=selected_filiere_id)
        if selected_semester_id:
            exam_summaries = exam_summaries.filter(subject__semester_id=selected_semester_id)
        if selected_year:
            exam_summaries = exam_summaries.filter(Q(academic_year__label__icontains=selected_year) | Q(academic_year_id=selected_year) | Q(year__icontains=selected_year))

        for exam in exam_summaries:
            subj = exam.subject
            if not subj:
                continue
            if subj.id not in subjects_map:
                subjects_map[subj.id] = {
                    "subject": subj,
                    "years": [],
                    "seen_keys": set(),
                }

            year_label = format_academic_year(exam.academic_year, exam.year)
            sort_year = parse_sort_year(exam.academic_year, exam.year)

            unique_key = f"{year_label}_exam_{exam.id}"
            if unique_key in subjects_map[subj.id]["seen_keys"]:
                continue
            subjects_map[subj.id]["seen_keys"].add(unique_key)

            is_locked = False
            if mode == "premium":
                is_locked = not can_user_access_summary(request.user, exam)

            viewer_url = reverse("exams:student_viewer", kwargs={"pk": exam.id}) + "?type=summary"
            subjects_map[subj.id]["years"].append({
                "year_label": year_label,
                "sort_year": sort_year,
                "title": f"Fiche résumé — {exam.title}",
                "session": "Fiche de synthèse",
                "exam_id": exam.id,
                "is_locked": is_locked,
                "viewer_url": viewer_url,
                "exam": exam,
            })

        # B. Résumés rédigés de cours
        course_summaries = CourseSummary.objects.filter(publication_status="PUBLISHED").select_related(
            "subject", "subject__semester", "subject__semester__filiere"
        )
        if mode == "free":
            course_summaries = course_summaries.filter(Q(access_type="FREE") | Q(subject__is_free_correction=True))

        if q:
            course_summaries = course_summaries.filter(
                Q(subject__name__icontains=q) |
                Q(subject__code__icontains=q) |
                Q(title__icontains=q) |
                Q(subject__semester__filiere__name__icontains=q) |
                Q(subject__semester__label__icontains=q)
            )
        if selected_subject_id:
            course_summaries = course_summaries.filter(subject_id=selected_subject_id)
        if selected_filiere_id:
            course_summaries = course_summaries.filter(subject__semester__filiere_id=selected_filiere_id)
        if selected_semester_id:
            course_summaries = course_summaries.filter(subject__semester_id=selected_semester_id)
        if selected_year:
            m = re.search(r"(\d{4})", selected_year)
            if m:
                course_summaries = course_summaries.filter(created_at__year=int(m.group(1)))

        for cs in course_summaries:
            subj = cs.subject
            if not subj:
                continue
            if subj.id not in subjects_map:
                subjects_map[subj.id] = {
                    "subject": subj,
                    "years": [],
                    "seen_keys": set(),
                }

            year_label = format_academic_year(None, None, cs.created_at)
            sort_year = parse_sort_year(None, None, cs.created_at)

            unique_key = f"{year_label}_cs_{cs.id}"
            if unique_key in subjects_map[subj.id]["seen_keys"]:
                continue
            subjects_map[subj.id]["seen_keys"].add(unique_key)

            is_locked = False
            if mode == "premium":
                is_locked = not (cs.is_free or has_user_valid_pass(request.user, cs))

            viewer_url = reverse("content:summary_detail", kwargs={"pk": cs.id})
            subjects_map[subj.id]["years"].append({
                "year_label": year_label,
                "sort_year": sort_year,
                "title": cs.title,
                "session": "Résumé de cours",
                "exam_id": None,
                "summary_id": cs.id,
                "is_locked": is_locked,
                "viewer_url": viewer_url,
                "summary_obj": cs,
            })

    # Trier les années de chaque UE de la plus récente à la plus ancienne
    ue_list = []
    for subj_id, data in subjects_map.items():
        data["years"].sort(key=lambda x: (x["sort_year"], x["year_label"]), reverse=True)
        data["years_count"] = len(data["years"])
        data["has_locked"] = any(y["is_locked"] for y in data["years"])
        data["all_locked"] = all(y["is_locked"] for y in data["years"]) if data["years"] else False

        # Regroupement propre par année académique pour affichage ergonomique
        grouped_dict = {}
        for y in data["years"]:
            lbl = y["year_label"]
            if lbl not in grouped_dict:
                grouped_dict[lbl] = {
                    "year_label": lbl,
                    "sort_year": y["sort_year"],
                    "items": [],
                    "has_locked": False,
                    "all_locked": True,
                }
            grouped_dict[lbl]["items"].append(y)
            if y["is_locked"]:
                grouped_dict[lbl]["has_locked"] = True
            else:
                grouped_dict[lbl]["all_locked"] = False

        data["years_grouped"] = sorted(
            grouped_dict.values(),
            key=lambda x: (x["sort_year"], x["year_label"]),
            reverse=True
        )
        ue_list.append(data)

    # Trier les UE par ordre alphabétique
    ue_list.sort(key=lambda x: x["subject"].name)

    total_resources_count = sum(item["years_count"] for item in ue_list)

    # Liste des matières disponibles pour la sélection rapide
    available_subjects_nav = [
        {
            "id": item["subject"].id,
            "name": item["subject"].name,
            "code": item["subject"].code,
            "years_count": item["years_count"],
        }
        for item in ue_list
    ]

    # Pagination : si une UE précise est demandée, on l'affiche directement sans la tronquer
    if selected_subject_id:
        page_obj = ue_list
    else:
        paginator = Paginator(ue_list, 12)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

    from subscriptions.services import user_has_any_active_pass
    user_has_any_pass = user_has_any_active_pass(request.user) if request.user.is_authenticated else False

    selected_subject = None
    if selected_subject_id:
        selected_subject = Subject.objects.filter(pk=selected_subject_id).select_related(
            "semester", "semester__filiere", "semester__filiere__school"
        ).first()

    all_exams = [y["exam"] for ue in ue_list for y in ue["years"] if y.get("exam")]

    context = {
        "mode": mode,
        "is_free_mode": mode == "free",
        "category": category,
        "page_obj": page_obj,
        "ue_list": page_obj,
        "all_ue_list": ue_list,
        "available_subjects_nav": available_subjects_nav,
        "exams": all_exams,
        "total_ue_count": len(ue_list),
        "total_resources_count": total_resources_count,
        "q": q,
        "selected_subject": selected_subject,
        "selected_subject_id": selected_subject_id,
        "selected_filiere_id": selected_filiere_id,
        "selected_semester_id": selected_semester_id,
        "selected_year": selected_year,
        "selected_type": selected_type,
        "user_has_any_pass": user_has_any_pass,
        "available_filieres": Filiere.objects.filter(is_active=True).select_related("school").order_by("school__name", "name"),
        "available_semesters": Semester.objects.filter(is_active=True).select_related("filiere").order_by("number", "label"),
        "available_academic_years": AcademicYear.objects.all().order_by("-label"),
        "exam_types": Exam.EXAM_TYPE_CHOICES,
    }
    return render(request, "exams/liste.html", context)


# Alias pour la compatibilité avec le code existant
exam_list = resources_view


def exam_detail(request, pk):
    """Page de détail d'une épreuve."""
    exam = get_object_or_404(
        Exam.objects.select_related(
            "subject", "semester", "filiere", "level", "academic_year", "filiere__school", "summary"
        ),
        pk=pk,
        is_published=True
    )

    if exam.subject and request.user.is_authenticated:
        from academics.models import record_ue_consultation
        record_ue_consultation(request.user, exam.subject, exam=exam)

    has_access = can_user_access_exam_pdf(request.user, exam)
    has_correction_access = can_user_access_correction(request.user, exam)
    has_summary_access = can_user_access_summary(request.user, exam)
    is_favorited = Favorite.objects.filter(user=request.user, exam=exam).exists() if request.user.is_authenticated else False

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

    disposition = "inline"
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

    disposition = "inline"
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

    disposition = "inline"
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
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
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
            <div class="icon"><i class="fa-solid fa-triangle-exclamation text-amber-400"></i></div>
            <h3>Document Indisponible</h3>
            <p>{message}</p>
        </div>
    </body>
    </html>
    """
    return HttpResponse(html_content, content_type="text/html", status=200)


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
        if not request.user.is_authenticated:
            messages.info(request, "Veuillez vous connecter et activer votre Pass pour consulter cette ressource.")
            return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
        messages.warning(
            request,
            "Cette ressource est réservée aux étudiants disposant du Pass actif pour ce semestre."
        )
        sem_id = exam.semester.id if exam.semester else (exam.subject.semester.id if exam.subject and exam.subject.semester else 1)
        return redirect("payments:pass_semestre", semester_id=sem_id)

    stream_url = reverse("exams:stream_watermarked_pdf", kwargs={"pk": exam.id}) + f"?type={res_type}"

    if exam.subject and request.user.is_authenticated:
        from academics.models import record_ue_consultation
        record_ue_consultation(request.user, exam.subject, exam=exam)

    context = {
        "exam": exam,
        "resource_label": resource_label,
        "res_type": res_type,
        "stream_url": stream_url,
    }
    return render(request, "exams/viewer.html", context)


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

    subj_name = exam.subject.name if exam.subject else "Document"
    safe_filename = _sanitize_header_filename(f"ArchivEx_{res_type}_{subj_name}_{exam.year}") + ".pdf"

    # 1. Vérification du cache serveur (réponse instantanée sous ~5ms)
    from django.core.cache import cache
    file_mtime = 0
    if isinstance(file_obj, str) and os.path.exists(file_obj):
        file_mtime = int(os.path.getmtime(file_obj))

    cache_key = f"wm_pdf_{exam.id}_{res_type}_{request.user.id}_{file_mtime}"
    from io import BytesIO
    cached_pdf = cache.get(cache_key)
    if cached_pdf:
        response = FileResponse(BytesIO(cached_pdf), content_type="application/pdf")
        response["Content-Length"] = len(cached_pdf)
        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = f'inline; filename="{safe_filename}"'
        return response

    try:
        watermarked_io = apply_student_watermark(file_obj, request.user)
        pdf_bytes = watermarked_io.getvalue()
        # Enregistrement en cache pour 3 heures (10800s)
        cache.set(cache_key, pdf_bytes, timeout=10800)

        response = FileResponse(BytesIO(pdf_bytes), content_type="application/pdf")
        response["Content-Length"] = len(pdf_bytes)
        response["Accept-Ranges"] = "bytes"
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
            response["Content-Disposition"] = f'inline; filename="{safe_filename}"'
            return response
        except Exception:
            return _render_pdf_error_response("Le fichier PDF n'a pas pu être lu par le serveur.")