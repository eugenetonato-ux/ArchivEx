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
    create_fedapay_transaction,
    verify_fedapay_webhook_signature,
    handle_fedapay_webhook_event,
    verify_and_sync_fedapay_transaction,
    create_chariow_checkout,
    verify_chariow_pulse_signature,
    handle_chariow_pulse_event,
    activate_pass_for_payment,
    verify_and_sync_chariow_sale,
)

logger = logging.getLogger(__name__)


@login_required
def pass_semestre(request, semester_id):
    """Page de présentation et formulaire de souscription du Pass Semestre (3 800 FCFA)."""
    from exams.models import Exam
    from content.models import Summary, Guide, Article
    from academics.models import Subject
    from django.db.models import Q

    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    price = getattr(settings, "PASS_SEMESTRE_PRIX_DEFAUT", 3800)

    already_active = SemesterAccess.objects.filter(
        user=request.user, semester=semester, activated_at__isnull=False
    ).exists()

    # Statistiques du package pour le semestre
    subjects = list(Subject.objects.filter(semester=semester))
    subjects_count = len(subjects)
    exams_count = Exam.objects.filter(semester=semester, is_published=True).count()
    summaries_count = Summary.objects.filter(subject__semester=semester, publication_status="PUBLISHED").count()
    guides_count = Guide.objects.filter(subject__semester=semester, publication_status="PUBLISHED").count()
    articles_count = Article.objects.filter(publication_status="PUBLISHED").filter(
        Q(target_filiere=semester.filiere) | Q(target_school=semester.filiere.school) | Q(target_filiere__isnull=True, target_school__isnull=True)
    ).count()

    sample_exams = Exam.objects.filter(semester=semester, is_published=True).select_related("subject")[:4]

    context = {
        "semester": semester,
        "price": price,
        "already_active": already_active,
        "subjects": subjects,
        "subjects_count": subjects_count,
        "sample_subjects": subjects,
        "exams_count": exams_count,
        "summaries_count": summaries_count,
        "guides_count": guides_count,
        "articles_count": articles_count,
        "sample_exams": sample_exams,
    }
    return render(request, "payments/pass_semestre.html", context)


@login_required
@require_POST
def initier_paiement(request, semester_id):
    """
    Initialise le paiement sécurisé côté serveur via FedaPay :
    - Détermine le tarif serveur (3 800 FCFA)
    - Valide et normalise le numéro béninois (+229)
    - Génère une référence externe unique (ARCHIVEX-PASS-YYYY-XXXXXX)
    - Crée l'enregistrement Payment local PENDING
    - Appelle l'API FedaPay (/v1/transactions + /token)
    - Redirige l'étudiant vers l'URL de paiement sécurisée FedaPay
    """
    semester = get_object_or_404(
        Semester.objects.select_related("filiere", "filiere__school", "filiere__level", "academic_year"),
        pk=semester_id
    )
    price = getattr(settings, "PASS_SEMESTRE_PRIX_DEFAUT", 3800)

    already_active = SemesterAccess.objects.filter(
        user=request.user, semester=semester, activated_at__isnull=False
    ).exists()

    if already_active:
        messages.info(request, "Vous disposez déjà d'un Pass actif pour ce semestre.")
        return redirect("academics:matieres", semester_id=semester.id)

    raw_phone = request.POST.get("phone_number", "").strip()

    try:
        normalized_phone = normalize_benin_phone(raw_phone)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("payments:pass_semestre", semester_id=semester.id)

    operator = request.POST.get("operator", "").strip().lower()
    if not operator:
        detected_op = detect_operator(normalized_phone)
        operator = detected_op or "fedapay"

    ext_ref = generate_external_reference()

    payment = Payment.objects.create(
        user=request.user,
        semester=semester,
        amount=price,
        currency=getattr(settings, "FEDAPAY_CURRENCY", getattr(settings, "CHARIOW_CURRENCY", "XOF")),
        operator=operator,
        phone_number=normalized_phone,
        external_reference=ext_ref,
        status=Payment.STATUS_PENDING,
    )

    # URL de retour sécurisée après la validation FedaPay
    return_url = reverse("payments:payment_return", kwargs={"reference": payment.external_reference})
    callback_url = request.build_absolute_uri(return_url)

    # Initialisation de la transaction via FedaPay (Gateway principale)
    fedapay_res = create_fedapay_transaction(payment, callback_url=callback_url)

    if fedapay_res.get("success"):
        checkout_url = fedapay_res.get("checkout_url")
        if checkout_url:
            return redirect(checkout_url)
        else:
            return redirect("payments:payment_pending", reference=payment.external_reference)
    else:
        # Fallback de secours vers Chariow si FedaPay échoue ou n'est pas encore configuré
        if getattr(settings, "CHARIOW_API_KEY", "") and getattr(settings, "CHARIOW_PRODUCT_ID", ""):
            logger.info("[Paiement] FedaPay non disponible, tentative de repli vers Chariow pour ref=%s", payment.external_reference)
            chariow_return_url = f"{callback_url}?sale_id={{sale_id}}"
            chariow_res = create_chariow_checkout(payment, redirect_url=chariow_return_url)
            if chariow_res.get("success") and chariow_res.get("checkout_url"):
                return redirect(chariow_res.get("checkout_url"))

        error_msg = fedapay_res.get("error", "Erreur lors de l'initialisation du paiement.")
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

    # Synchronisation immédiate avec l'API de paiement si pas encore approuvé
    if not payment.is_approved:
        if payment.fedapay_transaction_id:
            verify_and_sync_fedapay_transaction(payment)
        elif payment.chariow_sale_id:
            verify_and_sync_chariow_sale(payment)
        payment.refresh_from_db()

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
    Page de retour post-paiement FedaPay (ou Chariow legacy).
    Effectue une vérification active auprès de l'API FedaPay
    pour valider immédiatement le paiement et activer le Pass Semestre sans attendre le Webhook.
    """
    ref = reference or request.GET.get("external_reference") or request.GET.get("reference")
    tx_id = request.GET.get("id") or request.GET.get("transaction_id")
    sale_id = request.GET.get("sale_id") or request.GET.get("sale")
    payment = None

    if ref:
        payment = Payment.objects.filter(
            external_reference=ref, user=request.user
        ).select_related("semester", "semester__filiere").first()

    if not payment and tx_id:
        payment = Payment.objects.filter(
            fedapay_transaction_id=str(tx_id), user=request.user
        ).select_related("semester", "semester__filiere").first()

    if not payment and sale_id:
        payment = Payment.objects.filter(
            chariow_sale_id=sale_id, user=request.user
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

    # Synchronisation active directe avec l'API
    if not payment.is_approved:
        if payment.fedapay_transaction_id or tx_id:
            verify_and_sync_fedapay_transaction(payment, transaction_id=tx_id)
        elif payment.chariow_sale_id or sale_id:
            verify_and_sync_chariow_sale(payment, sale_id=sale_id)
        payment.refresh_from_db()

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
    Interroge l'API FedaPay si le paiement local est encore PENDING pour une confirmation temps réel.
    """
    payment = get_object_or_404(Payment, external_reference=reference, user=request.user)

    if not payment.is_approved:
        tx_id = request.GET.get("id") or request.GET.get("transaction_id") or payment.fedapay_transaction_id
        sale_id = request.GET.get("sale_id") or payment.chariow_sale_id

        if tx_id:
            verify_and_sync_fedapay_transaction(payment, transaction_id=tx_id)
        elif sale_id:
            verify_and_sync_chariow_sale(payment, sale_id=sale_id)
        payment.refresh_from_db()

    return JsonResponse({
        "reference": payment.external_reference,
        "status": payment.status,
        "is_approved": payment.is_approved,
        "is_rejected": payment.is_rejected,
        "is_pending": payment.is_pending,
        "fedapay_transaction_id": payment.fedapay_transaction_id,
        "chariow_sale_id": payment.chariow_sale_id,
    })


@csrf_exempt
@require_POST
def fedapay_webhook_view(request):
    """
    Endpoint Webhook sécurisé pour la réception des notifications d'événements FedaPay.
    POST /pass/webhook/fedapay/ et POST /webhook/fedapay/
    
    Sécurité & Idempotence :
    1. Vérification de la signature HMAC-SHA256 (header X-FEDAPAY-SIGNATURE)
    2. Décodage du payload JSON
    3. Traitement des événements (transaction.approved, transaction.transferred, transaction.declined, transaction.canceled)
    4. Réponse HTTP 200 JSON
    """
    signature_header = (
        request.headers.get("X-FEDAPAY-SIGNATURE") or
        request.headers.get("x-fedapay-signature") or
        request.META.get("HTTP_X_FEDAPAY_SIGNATURE", "")
    )

    if not verify_fedapay_webhook_signature(request.body, signature_header):
        logger.warning("[FedaPay Webhook] Signature webhook invalide reçue.")
        return HttpResponseForbidden("Signature Webhook FedaPay invalide.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("[FedaPay Webhook] Payload JSON non décodable.")
        return JsonResponse({"error": "Payload JSON invalide"}, status=400)

    result = handle_fedapay_webhook_event(payload)
    status_code = 200 if result.get("success", True) else result.get("status_code", 400)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
def chariow_webhook_view(request):
    """
    Endpoint Webhook hérité pour la réception des Pulses Chariow (legacy / fallback).
    POST /pass/webhook/chariow/ et POST /webhook/chariow/
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