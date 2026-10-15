"""Services académiques pour la gestion du cycle des semestres et des accès."""
import logging
from django.db import transaction
from django.db.models import Count, Q
from academics.models import Semester, Subject
from exams.models import Exam

logger = logging.getLogger(__name__)


def get_semesters_summary():
    """
    Retourne un résumé complet de l'état de chaque numéro de semestre (S1, S2, etc.)
    ainsi que le détail par filière pour l'administration.
    """
    # Regroupement par numéro de semestre (1, 2, etc.)
    numbers = Semester.objects.values_list("number", flat=True).distinct().order_by("number")
    summary = []

    for num in numbers:
        semesters_qs = Semester.objects.filter(number=num)
        total_sems = semesters_qs.count()
        active_sems = semesters_qs.filter(is_active=True).count()
        is_fully_active = (active_sems == total_sems and total_sems > 0)
        is_partially_active = (0 < active_sems < total_sems)

        subjects_qs = Subject.objects.filter(semester__number=num)
        total_subjects = subjects_qs.count()
        active_subjects = subjects_qs.filter(is_active=True).count()

        exams_qs = Exam.objects.filter(semester__number=num)
        total_exams = exams_qs.count()
        published_exams = exams_qs.filter(is_published=True).count()

        summary.append({
            "number": num,
            "label": f"Semestre {num}",
            "is_active": is_fully_active,
            "is_partially_active": is_partially_active,
            "total_semesters": total_sems,
            "active_semesters": active_sems,
            "total_subjects": total_subjects,
            "active_subjects": active_subjects,
            "total_exams": total_exams,
            "published_exams": published_exams,
            "semesters_list": list(semesters_qs.select_related("filiere", "filiere__school").order_by("filiere__name")),
        })

    return summary


@transaction.atomic
def set_exclusive_active_semester(number):
    """
    Définit le semestre `number` (ex: 1) comme le SEUL semestre actif sur toute la plateforme.
    Tous les autres semestres (ex: 2) sont automatiquement masqués / désactivés.
    - Active tous les semestres avec number = number
    - Active leurs matières et publie leurs épreuves
    - Désactive tous les autres semestres, masque leurs matières et dépublie leurs épreuves
    """
    # 1. Activer le semestre cible
    target_sems = Semester.objects.filter(number=number)
    target_sems.update(is_active=True)
    Subject.objects.filter(semester__number=number).update(is_active=True)
    Exam.objects.filter(semester__number=number).update(is_published=True)

    # 2. Désactiver tous les autres semestres
    other_sems = Semester.objects.exclude(number=number)
    other_sems.update(is_active=False)
    Subject.objects.exclude(semester__number=number).update(is_active=False)
    Exam.objects.exclude(semester__number=number).update(is_published=False)

    logger.info(f"[Semester Control] Semestre {number} activé exclusivement sur toute la plateforme.")
    return True


@transaction.atomic
def activate_semester_number(number):
    """Active tous les semestres portant ce numéro."""
    Semester.objects.filter(number=number).update(is_active=True)
    Subject.objects.filter(semester__number=number).update(is_active=True)
    Exam.objects.filter(semester__number=number).update(is_published=True)
    logger.info(f"[Semester Control] Semestre {number} activé.")
    return True


@transaction.atomic
def deactivate_semester_number(number):
    """Désactive et masque tous les semestres portant ce numéro."""
    Semester.objects.filter(number=number).update(is_active=False)
    Subject.objects.filter(semester__number=number).update(is_active=False)
    Exam.objects.filter(semester__number=number).update(is_published=False)
    logger.info(f"[Semester Control] Semestre {number} désactivé.")
    return True


@transaction.atomic
def toggle_semester_active(semester_id):
    """Bascule l'état d'un semestre spécifique."""
    sem = Semester.objects.filter(pk=semester_id).first()
    if not sem:
        return False
    new_status = not sem.is_active
    sem.is_active = new_status
    sem.save(update_fields=["is_active"])
    Subject.objects.filter(semester=sem).update(is_active=new_status)
    Exam.objects.filter(semester=sem).update(is_published=new_status)
    return new_status
