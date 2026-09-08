import json
import logging
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse, Http404

from academics.models import Semester
from .models import SemesterAccess, Payment
from .services import (
    normalize_benin_phone,
    detect_operator,
    generate_external_reference,
    create_chariow_checkout,
    verify_chariow_pulse_signature,
    handle_chariow_pulse_event,
    activate_pass_for_payment,
)

logger = logging.getLogger(__name__)


@login_required
def pass_semestre(request, semester_id):
    """Page de présentation et formulaire de souscription du Pass Semestre (2 000 FCFA)."""
    from exams.models import Exam
    from content.models import Summary, Guide, Article
    from academics.models import Subject
    from django.db.models import Q

    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    price = getattr(settings, "PASS_SEMESTRE_PRIX_DEFAUT", 4500)

    already_active = SemesterAccess.objects.filter(
        user=request.user, semester=semester, activated_at__isnull=False
    ).exists()

    # Statistiques du package pour le semestre
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
    """
    Initialise le paiement sécurisé côté serveur :
    - Détermine le tarif serveur (2 000 FCFA)
    - Valide et normalise le numéro béninois
    - Génère une référence externe unique (ARCHIVEX-PASS-YYYY-XXXXXX)
    - Crée l'enregistrement Payment local PENDING
    - Appelle l'API Chariow /checkout
    - Redirige l'étudiant vers payment.checkout_url
    """
    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    price = getattr(settings, "PASS_SEMESTRE_PRIX_DEFAUT", 4500)

    already_active = SemesterAccess.objects.filter(
        user=request.user, semester=semester, activated_at__isnull=False
    ).exists()

    if already_active:
        messages.info(request, "Vous disposez déjà d'un Pass actif pour ce semestre.")
        return redirect("academics:matieres", semester_id=semester.id)

    operator = request.POST.get("operator", "mtn").strip().lower()
    raw_phone = request.POST.get("phone_number", "").strip()

    try:
        normalized_phone = normalize_benin_phone(raw_phone)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("payments:pass_semestre", semester_id=semester.id)

    detected_op = detect_operator(normalized_phone)
    if detected_op in ["mtn", "moov"]:
        operator = detected_op
    elif operator not in ["mtn", "moov"]:
        operator = "mtn"

    ext_ref = generate_external_reference()

    payment = Payment.objects.create(
        user=request.user,
        semester=semester,
        amount=price,
        currency=getattr(settings, "CHARIOW_CURRENCY", "XOF"),
        operator=operator,
        phone_number=normalized_phone,
        external_reference=ext_ref,
        status=Payment.STATUS_PENDING,
    )

    redirect_url = request.build_absolute_uri(
        reverse("payments:payment_return", kwargs={"reference": payment.external_reference})
    )

    # Appel à l'API Chariow Checkout (/v1/checkout)
    chariow_res = create_chariow_checkout(payment, redirect_url=redirect_url)

    if chariow_res.get("success"):
        checkout_url = chariow_res.get("checkout_url")
        if checkout_url:
            return redirect(checkout_url)
        elif chariow_res.get("step") == "completed":
            # Produit validé immédiatement
            activate_pass_for_payment(payment)
            messages.success(request, f"Félicitations ! Votre Pass Semestre pour {semester.label} est actif !")
            return redirect("academics:matieres", semester_id=semester.id)
        else:
            return redirect("payments:payment_pending", reference=payment.external_reference)
    else:
        error_msg = chariow_res.get("error", "Erreur lors de l'initialisation du paiement.")
        payment.status = Payment.STATUS_REJECTED
        payment.save(update_fields=["status"])
        messages.error(request, error_msg)
        return redirect("payments:pass_semestre", semester_id=semester.id)


@login_required
def payment_pending_view(request, reference):
    """Écran d'attente de confirmation de la transaction avec sondage asynchrone."""
    payment = get_object_or_404(
        Payment.objects.select_related("semester", "semester__filiere"),
        external_reference=reference,
        user=request.user
    )

    if payment.is_approved:
        messages.success(request, f"Félicitations ! Votre Pass Semestre pour {payment.semester.label} est actif !")
        return redirect("academics:matieres", semester_id=payment.semester.id)

    context = {
        "payment": payment,
        "semester": payment.semester,
    }
    return render(request, "payments/pending.html", context)


@login_required
def payment_return_view(request, reference=None):
    """
    Page de retour post-paiement Chariow (redirect_url).
    
    IMPORTANT :
    Cette page sert à l'expérience utilisateur. La source de vérité reste le webhook Pulse.
    Le statut affiché correspond strictement à l'état en base de données.
    """
    ref = reference or request.GET.get("external_reference") or request.GET.get("reference")
    payment = None

    if ref:
        payment = Payment.objects.filter(
            external_reference=ref, user=request.user
        ).select_related("semester", "semester__filiere").first()

    if not payment:
        payment = Payment.objects.filter(
            user=request.user
        ).select_related("semester", "semester__filiere").order_by("-created_at").first()

    if not payment:
        first_sem = Semester.objects.first()
        return render(request, "payments/return.html", {
            "payment": None,
            "semester": first_sem,
            "is_approved": False,
            "is_pending": False,
            "is_rejected": True,
        })

    context = {
        "payment": payment,
        "semester": payment.semester,
        "status": payment.status,
        "is_approved": payment.is_approved,
        "is_pending": payment.is_pending,
        "is_rejected": payment.is_rejected,
    }
    return render(request, "payments/return.html", context)


@login_required
def payment_status_api_view(request, reference):
    """
    API JSON d'état pour le sondage dynamique depuis les pages d'attente / retour.
    """
    payment = get_object_or_404(Payment, external_reference=reference, user=request.user)

    return JsonResponse({
        "reference": payment.external_reference,
        "status": payment.status,
        "is_approved": payment.is_approved,
        "is_rejected": payment.is_rejected,
        "is_pending": payment.is_pending,
        "chariow_sale_id": payment.chariow_sale_id,
    })


@csrf_exempt
@require_POST
def chariow_webhook_view(request):
    """
    Endpoint Webhook sécurisé pour la réception des Pulses Chariow.
    POST /pass/webhook/chariow/ et POST /webhook/chariow/
    
    Sécurité & Idempotence :
    1. Vérification de la signature HMAC-SHA256 (header x-chariow-signature)
    2. Dé-duplication via x-pulse-delivery-id et external_reference
    3. Traitement des événements (successful.sale, failed.sale, abandoned.sale, refunded.sale)
    4. Réponse HTTP 200 JSON
    """
    signature_header = (
        request.headers.get("X-Chariow-Signature") or
        request.headers.get("x-chariow-signature") or
        request.META.get("HTTP_X_CHARIOW_SIGNATURE", "")
    )

    if not verify_chariow_pulse_signature(request.body, signature_header):
        logger.warning("[Chariow Webhook] Signature invalide reçue.")
        return HttpResponseForbidden("Signature Webhook Chariow invalide.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("[Chariow Webhook] Payload JSON non décodable.")
        return JsonResponse({"error": "Payload JSON invalide"}, status=400)

    delivery_id = (
        request.headers.get("X-Pulse-Delivery-Id") or
        request.headers.get("x-pulse-delivery-id") or
        request.META.get("HTTP_X_PULSE_DELIVERY_ID", "")
    )

    result = handle_chariow_pulse_event(payload, delivery_id=delivery_id)

    status_code = 200 if result.get("success", True) else result.get("status_code", 400)
    return JsonResponse(result, status=status_code)


@login_required
def student_payment_history_view(request):
    """Historique des transactions et Pass Semestre de l'étudiant."""
    payments = Payment.objects.filter(
        user=request.user
    ).select_related("semester", "semester__filiere").order_by("-created_at")

    context = {
        "payments": payments,
    }
    return render(request, "payments/history.html", context)