from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST

from academics.models import Semester
from .models import SemesterAccess, Payment


@login_required
def pass_semestre(request, semester_id):
    """Page de présentation du Pass Semestre avec tarif serveur et package dynamique."""
    from exams.models import Exam
    from content.models import Summary, Guide, Article
    from academics.models import Subject
    from django.db.models import Q

    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    price = settings.PASS_SEMESTRE_PRIX_DEFAUT

    already_active = SemesterAccess.objects.filter(
        user=request.user, semester=semester, activated_at__isnull=False
    ).exists()

    # Dynamic resource package counts for this semester
    exams_count = Exam.objects.filter(semester=semester, is_published=True).count()
    summaries_count = Summary.objects.filter(subject__semester=semester, publication_status="PUBLISHED").count()
    guides_count = Guide.objects.filter(subject__semester=semester, publication_status="PUBLISHED").count()
    articles_count = Article.objects.filter(publication_status="PUBLISHED").filter(
        Q(target_filiere=semester.filiere) | Q(target_school=semester.filiere.school) | Q(target_filiere__isnull=True, target_school__isnull=True)
    ).count()

    sample_subjects = Subject.objects.filter(semester=semester)[:6]
    sample_exams = Exam.objects.filter(semester=semester, is_published=True).select_related("subject")[:4]

    context = {
        "semester": semester,
        "price": price,
        "already_active": already_active,
        "exams_count": exams_count,
        "summaries_count": summaries_count,
        "guides_count": guides_count,
        "articles_count": articles_count,
        "sample_subjects": sample_subjects,
        "sample_exams": sample_exams,
    }
    return render(request, "payments/pass_semestre.html", context)



@login_required
@require_POST
def initier_paiement(request, semester_id):
    """Crée ou récupère l'accès en attente et enregistre la transaction avec montant serveur.

    Protégé par @require_POST : cette action crée un enregistrement en base
    (SemesterAccess + Payment) et ne doit pas pouvoir être déclenchée par un
    simple GET (lien direct, prefetch de navigateur, etc.).
    """
    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    price = settings.PASS_SEMESTRE_PRIX_DEFAUT

    already_active = SemesterAccess.objects.filter(
        user=request.user, semester=semester, activated_at__isnull=False
    ).exists()

    if already_active:
        messages.info(request, "Tu disposais déjà d'un Pass actif pour ce semestre.")
        return redirect("academics:matieres", semester_id=semester.id)

    access, _ = SemesterAccess.objects.get_or_create(
        user=request.user,
        semester=semester,
        defaults={
            "school": semester.filiere.school,
            "level": semester.filiere.level,
            "filiere": semester.filiere,
            "academic_year": semester.academic_year,
        },
    )

    # Récupérer un paiement en attente ou en créer un nouveau
    payment = Payment.objects.filter(
        user=request.user, semester_access=access, status="en_attente"
    ).last()

    if not payment:
        payment = Payment.objects.create(
            user=request.user,
            semester_access=access,
            amount=price,  # Montant déterminé EXCLUSIVEMENT côté serveur
            status="en_attente",
        )

    context = {
        "semester": semester,
        "payment": payment,
        "price": price,
    }
    return render(request, "payments/paiement.html", context)


@login_required
@require_POST
def confirmer_paiement(request, payment_id):
    """
    Simule la confirmation serveur d'un paiement (callback / webhook).
    Active le SemesterAccess et crée un UserSubscription valide 180 jours.
    """
    from datetime import timedelta
    from subscriptions.models import UserSubscription

    payment = get_object_or_404(Payment, pk=payment_id, user=request.user)

    if payment.status == "en_attente":
        now = timezone.now()
        payment.status = "reussi"
        payment.paid_at = now
        payment.save()

        access = payment.semester_access
        if not access.activated_at:
            access.activated_at = now
            access.save()

        # Créer / Activer l'abonnement V2
        UserSubscription.objects.get_or_create(
            user=request.user,
            semester=access.semester,
            filiere=access.filiere,
            school=access.school,
            payment=payment,
            defaults={
                "start_date": now,
                "end_date": now + timedelta(days=180),
                "is_active": True,
            }
        )

        messages.success(
            request,
            f"🎉 Félicitations ! Ton Pass pour le {access.semester.label} est désormais débloqué !"
        )

    context = {
        "payment": payment,
        "confirmed": True,
        "semester": payment.semester_access.semester,
    }
    return render(request, "payments/paiement.html", context)