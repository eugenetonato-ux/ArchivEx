import json
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse, Http404

from academics.models import Semester
from .models import SemesterAccess, Payment
from .services import (
    normalize_benin_phone,
    generate_external_reference,
    create_sebpay_collection,
    verify_sebpay_transaction,
    verify_webhook_signature,
    activate_pass_for_payment,
)


@login_required
def pass_semestre(request, semester_id):
    """Page de présentation et formulaire de souscription du Pass Semestre (MTN, Moov, Celtiis)."""
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

    # Statistique dynamique du package
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
    Initié de façon sécurisée côté serveur :
    - Détermine le tarif serveur (jamais soumis par le navigateur)
    - Normalise le numéro béninois (229XXXXXXXX)
    - Génère une référence externe unique (ARCHIVEX-PASS-YYYY-XXXXXX)
    - Crée l'enregistrement Payment local PENDING
    - Transmet la requête d'encaissement à SebPay
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
    if operator not in ["mtn", "moov", "celtiis"]:
        messages.error(request, "Veuillez sélectionner un opérateur Mobile Money valide (MTN, Moov ou Celtiis).")
        return redirect("payments:pass_semestre", semester_id=semester.id)

    raw_phone = request.POST.get("phone_number", "").strip()
    try:
        normalized_phone = normalize_benin_phone(raw_phone)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("payments:pass_semestre", semester_id=semester.id)

    ext_ref = generate_external_reference()

    payment = Payment.objects.create(
        user=request.user,
        semester=semester,
        amount=price,  # Montant déterminé STRICTEMENT par le serveur
        currency=getattr(settings, "SEBPAY_CURRENCY", "XOF"),
        operator=operator,
        phone_number=normalized_phone,
        external_reference=ext_ref,
        status=Payment.STATUS_PENDING,
    )

    # Lancer l'encaissement SebPay
    sebpay_res = create_sebpay_collection(payment)

    if not sebpay_res.get("success"):
        messages.warning(
            request,
            f"La demande de paiement n'a pas pu être transmise automatiquement. "
            f"Veuillez valider sur votre téléphone si le SMS apparaît ou réessayer."
        )

    return redirect("payments:payment_pending", reference=payment.external_reference)


@login_required
def payment_pending_view(request, reference):
    """Écran d'attente de confirmation Mobile Money avec sondage d'état."""
    payment = get_object_or_404(Payment.objects.select_related("semester", "semester__filiere"), external_reference=reference, user=request.user)

    if payment.is_approved:
        messages.success(request, f"🎉 Félicitations ! Votre Pass Semestre pour {payment.semester.label} est actif !")
        return redirect("academics:matieres", semester_id=payment.semester.id)

    context = {
        "payment": payment,
        "semester": payment.semester,
    }
    return render(request, "payments/pending.html", context)


@login_required
def payment_status_api_view(request, reference):
    """
    API JSON d'état pour le sondage AJAX de l'écran d'attente.
    Retourne le statut actuel et effectue une synchronisation complémentaire si demandé.
    """
    payment = get_object_or_404(Payment, external_reference=reference, user=request.user)

    # Synchronisation complémentaire auprès de SebPay si encore PENDING
    if payment.status in [Payment.STATUS_PENDING, "en_attente"] and request.GET.get("check_remote") == "1":
        remote_res = verify_sebpay_transaction(payment.external_reference)
        if remote_res.get("success"):
            data = remote_res.get("data", {})
            remote_status = str(data.get("status", "")).lower()
            if remote_status in ["approved", "success", "completed"]:
                payment.status = Payment.STATUS_APPROVED
                payment.sebpay_transaction_id = str(data.get("id") or data.get("reference") or payment.sebpay_transaction_id)
                activate_pass_for_payment(payment)
            elif remote_status in ["rejected", "failed", "cancelled"]:
                payment.status = Payment.STATUS_REJECTED
                payment.save()

    return JsonResponse({
        "reference": payment.external_reference,
        "status": payment.status,
        "is_approved": payment.is_approved,
        "is_rejected": payment.is_rejected,
        "is_pending": payment.is_pending,
    })


@csrf_exempt
def sebpay_webhook_view(request):
    """
    Endpoint de Webhook sécurisé pour la notification asynchrone des paiements SebPay.
    POST /webhook/sebpay/
    1. Vérification de la signature HMAC-SHA256 (header X-SebPay-Signature)
    2. Contrôle d'intégrité (montant & devise)
    3. Idempotence stricte (ne duplique pas l'activation du Pass)
    4. Activation du Pass Semestre lorsque statut est 'approved'
    """
    if request.method != "POST":
        return HttpResponse("Méthode non autorisée", status=405)

    signature_header = request.headers.get("X-SebPay-Signature") or request.META.get("HTTP_X_SEBPAY_SIGNATURE", "")

    if not verify_webhook_signature(request.body, signature_header):
        return HttpResponseForbidden("Signature Webhook SebPay invalide.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Payload JSON invalide"}, status=400)

    ext_ref = payload.get("external_reference") or payload.get("reference")
    if not ext_ref:
        return JsonResponse({"error": "Référence externe manquante"}, status=400)

    payment = Payment.objects.filter(external_reference=ext_ref).first()
    if not payment:
        return JsonResponse({"error": "Paiement introuvable"}, status=404)

    # Vérification d'intégrité sur montant et devise
    payload_amount = payload.get("amount")
    if payload_amount is not None and int(payload_amount) != int(payment.amount):
        return JsonResponse({"error": "Montant non conforme"}, status=400)

    # Traitement Idempotent : Si déjà APPROVED, retourner 200 immédiatement sans dupliquer
    if payment.is_approved:
        return JsonResponse({"status": "already_approved", "message": "Paiement déjà validé."})

    sebpay_status = str(payload.get("status", "")).lower()

    if sebpay_status in ["approved", "success", "completed"]:
        payment.status = Payment.STATUS_APPROVED
        payment.sebpay_transaction_id = str(payload.get("id") or payload.get("transaction_id") or payment.sebpay_transaction_id)
        activate_pass_for_payment(payment)
        return JsonResponse({"status": "approved", "message": "Pass Semestre activé avec succès."})

    elif sebpay_status in ["rejected", "failed", "cancelled"]:
        payment.status = Payment.STATUS_REJECTED
        payment.save()
        return JsonResponse({"status": "rejected", "message": "Paiement non confirmé."})

    return JsonResponse({"status": payment.status, "message": "Statut reçu."})


@login_required
def student_payment_history_view(request):
    """Historique personnel des transactions et Pass Semestre de l'étudiant."""
    payments = Payment.objects.filter(user=request.user).select_related("semester", "semester__filiere").order_by("-created_at")

    context = {
        "payments": payments,
    }
    return render(request, "payments/history.html", context)