"""Services de paiement et intégration Chariow API (https://chariow.dev).

Ce module gère :
- L'appel à l'API Chariow Checkout (/v1/checkout)
- La vérification des signatures HMAC-SHA256 des webhooks Pulses (header x-chariow-signature)
- Le traitement idempotent des événements Chariow (successful.sale, failed.sale, etc.)
- L'activation sécurisée et atomique des accès Pass Semestre (180 jours)
- La normalisation et validation des numéros mobiles (Bénin).
"""

import hmac
import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from .models import Payment, SemesterAccess
from subscriptions.models import UserSubscription

logger = logging.getLogger(__name__)

_TIMEOUT = 20

# Pays et devise par défaut (Bénin / UEMOA)
DEFAULT_COUNTRY = "BJ"
DEFAULT_CURRENCY = "XOF"

# Opérateurs béninois
OPERATOR_MTN = "mtn"
OPERATOR_MOOV = "moov"
SUPPORTED_OPERATORS = [OPERATOR_MTN, OPERATOR_MOOV]

# Indicatifs mobiles béninois (ARCEP 10 chiffres / 8 chiffres)
_BJ_MOBILE_PREFIXES = {
    "42": OPERATOR_MTN, "46": OPERATOR_MTN, "50": OPERATOR_MTN, "51": OPERATOR_MTN,
    "52": OPERATOR_MTN, "53": OPERATOR_MTN, "54": OPERATOR_MTN, "56": OPERATOR_MTN,
    "57": OPERATOR_MTN, "59": OPERATOR_MTN, "61": OPERATOR_MTN, "62": OPERATOR_MTN,
    "66": OPERATOR_MTN, "67": OPERATOR_MTN, "69": OPERATOR_MTN, "90": OPERATOR_MTN,
    "91": OPERATOR_MTN, "96": OPERATOR_MTN, "97": OPERATOR_MTN,
    "45": OPERATOR_MOOV, "55": OPERATOR_MOOV, "58": OPERATOR_MOOV, "60": OPERATOR_MOOV,
    "63": OPERATOR_MOOV, "64": OPERATOR_MOOV, "65": OPERATOR_MOOV, "68": OPERATOR_MOOV,
    "94": OPERATOR_MOOV, "95": OPERATOR_MOOV, "98": OPERATOR_MOOV, "99": OPERATOR_MOOV,
}


def _chariow_headers():
    """Génère les headers d'authentification pour l'API Chariow."""
    api_key = getattr(settings, "CHARIOW_API_KEY", "")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def detect_operator(phone_input):
    """
    Détecte l'opérateur béninois (mtn ou moov) à partir du numéro.
    Supporte les formats 8 chiffres, 10 chiffres (01XXXXXXXX) ou 13 chiffres (22901XXXXXXXX).
    """
    if not phone_input:
        return None

    cleaned = re.sub(r"[^\d]", "", str(phone_input))

    if cleaned.startswith("00229"):
        cleaned = cleaned[5:]
    elif cleaned.startswith("229"):
        cleaned = cleaned[3:]

    # Format national 10 chiffres (01XXXXXXXX)
    if len(cleaned) == 10 and cleaned.startswith("01"):
        indicator = cleaned[2:4]
        return _BJ_MOBILE_PREFIXES.get(indicator)

    # Ancien format 8 chiffres
    if len(cleaned) == 8:
        indicator = cleaned[0:2]
        return _BJ_MOBILE_PREFIXES.get(indicator)

    return None


def normalize_benin_phone(phone_input):
    """
    Normalise un numéro de téléphone béninois.
    Exemples acceptés :
      - '0150196407' -> '2290150196407'
      - '50196407' -> '2290150196407'
      - '+229 01 50 19 64 07' -> '2290150196407'
    """
    if not phone_input:
        raise ValueError("Le numéro de téléphone est obligatoire.")

    cleaned = re.sub(r"[^\d]", "", str(phone_input))

    if cleaned.startswith("00229"):
        cleaned = cleaned[5:]
    elif cleaned.startswith("229"):
        cleaned = cleaned[3:]

    if len(cleaned) == 8:
        cleaned = f"01{cleaned}"

    if len(cleaned) != 10 or not cleaned.startswith("01"):
        raise ValueError(
            "Numéro béninois invalide. Exemple attendu : 01 50 19 64 07 ou 50 19 64 07."
        )

    return f"229{cleaned}"


def generate_external_reference():
    """Génère une référence transactionnelle unique pour ArchivEx."""
    year = timezone.now().year
    code = uuid.uuid4().hex[:6].upper()
    ref = f"ARCHIVEX-PASS-{year}-{code}"
    while Payment.objects.filter(external_reference=ref).exists():
        code = uuid.uuid4().hex[:6].upper()
        ref = f"ARCHIVEX-PASS-{year}-{code}"
    return ref


def create_chariow_checkout(payment, redirect_url=None):
    """
    Initialise une session de paiement sécurisée via l'API Chariow Checkout.
    POST https://api.chariow.com/v1/checkout

    Transmet :
    - product_id (configuré dans CHARIOW_PRODUCT_ID)
    - email client
    - first_name / last_name
    - phone (objet {number, country_code})
    - redirect_url (page de retour ArchivEx)
    - custom_metadata (pour corréler le Pulse webhook)
    """
    api_key = getattr(settings, "CHARIOW_API_KEY", "")
    product_id = getattr(settings, "CHARIOW_PRODUCT_ID", "")
    base_url = getattr(settings, "CHARIOW_BASE_URL", "https://api.chariow.com/v1").rstrip("/")

    if not api_key:
        logger.error("[Chariow] CHARIOW_API_KEY non configurée dans settings / .env.")
        return {
            "success": False,
            "error": "Le service de paiement est temporairement indisponible (clé API non configurée).",
        }

    if not product_id:
        logger.error("[Chariow] CHARIOW_PRODUCT_ID non configuré dans settings / .env.")
        return {
            "success": False,
            "error": "Le produit Pass Semestre n'est pas encore lié à Chariow (ID produit manquant).",
        }

    user = payment.user
    email = getattr(user, "email", None) or f"{user.username}@archivex.bj"
    first_name = getattr(user, "first_name", "") or user.username
    last_name = getattr(user, "last_name", "") or ""

    # Nettoyage du numéro pour l'objet phone
    phone_digits = re.sub(r"[^\d]", "", str(payment.phone_number or ""))
    # Si le numéro commence par l'indicatif 229, on extrait les 10 chiffres nationaux
    if phone_digits.startswith("229") and len(phone_digits) == 13:
        national_number = phone_digits[3:]
    else:
        national_number = phone_digits

    payload = {
        "product_id": product_id,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "redirect_url": redirect_url or "",
        "custom_metadata": {
            "archivex_user_id": str(user.id),
            "archivex_semester_id": str(payment.semester_id) if payment.semester_id else "",
            "archivex_payment_id": str(payment.id),
            "external_reference": payment.external_reference,
            "plan": "semester_pass",
        }
    }

    if national_number:
        payload["phone"] = {
            "number": national_number,
            "country_code": DEFAULT_COUNTRY,
        }

    url = f"{base_url}/checkout"
    headers = _chariow_headers()

    try:
        logger.info(
            "[Chariow] Initialisation checkout ref=%s, user=%s, product_id=%s",
            payment.external_reference, user.username, product_id
        )
        response = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)

        try:
            res_data = response.json()
        except Exception:
            res_data = {"raw": response.text}

        if response.status_code in [200, 201]:
            step = res_data.get("step") or (res_data.get("data", {}).get("step") if isinstance(res_data.get("data"), dict) else "payment")
            
            # Extraction du checkout_url selon la structure de réponse
            checkout_url = (
                res_data.get("checkout_url") or
                res_data.get("payment_url") or
                res_data.get("url")
            )
            if not checkout_url and isinstance(res_data.get("payment"), dict):
                checkout_url = res_data["payment"].get("checkout_url") or res_data["payment"].get("url")
            if not checkout_url and isinstance(res_data.get("data"), dict):
                data_dict = res_data["data"]
                checkout_url = data_dict.get("checkout_url") or data_dict.get("payment_url") or data_dict.get("url")
                if not checkout_url and isinstance(data_dict.get("payment"), dict):
                    checkout_url = data_dict["payment"].get("checkout_url")

            # Extraction de la référence de vente / transaction
            sale_id = (
                res_data.get("sale_id") or
                res_data.get("transaction_id") or
                res_data.get("id")
            )
            if not sale_id and isinstance(res_data.get("data"), dict):
                sale_id = res_data["data"].get("sale_id") or res_data["data"].get("id")

            # Sauvegarde dans le modèle Payment
            if checkout_url:
                payment.chariow_checkout_url = checkout_url
            if sale_id:
                payment.chariow_sale_id = str(sale_id)
            payment.save(update_fields=["chariow_checkout_url", "chariow_sale_id"])

            return {
                "success": True,
                "step": step,
                "checkout_url": checkout_url,
                "sale_id": sale_id,
                "data": res_data,
            }

        # Gestion des erreurs renvoyées par l'API Chariow
        error_msg = (
            res_data.get("message") or
            res_data.get("error") or
            f"Erreur API Chariow (HTTP {response.status_code})"
        )
        logger.warning(
            "[Chariow] Échec Checkout HTTP %s pour ref=%s : %s",
            response.status_code, payment.external_reference, error_msg
        )
        return {
            "success": False,
            "error": error_msg,
            "status_code": response.status_code,
            "data": res_data,
        }

    except requests.exceptions.Timeout:
        logger.error("[Chariow] Timeout lors de l'appel /checkout pour ref=%s", payment.external_reference)
        return {"success": False, "error": "Le service Chariow n'a pas répondu à temps. Veuillez réessayer."}
    except requests.exceptions.RequestException as e:
        logger.error("[Chariow] Exception de connexion lors de l'appel /checkout : %s", e)
        return {"success": False, "error": "Erreur de communication avec la plateforme de paiement Chariow."}


def verify_chariow_pulse_signature(raw_body, signature_header):
    """
    Vérifie la signature HMAC-SHA256 du webhook Pulse transmise dans l'en-tête 'x-chariow-signature'.
    
    Format attendu selon la documentation Chariow :
    'sha256=<64 lowercase hex characters>' ou '<64 lowercase hex characters>'
    """
    pulse_secret = getattr(settings, "CHARIOW_PULSE_SECRET", "")
    if not pulse_secret or not signature_header or not raw_body:
        return False

    if isinstance(raw_body, str):
        raw_body_bytes = raw_body.encode("utf-8")
    else:
        raw_body_bytes = raw_body

    secret_bytes = pulse_secret.encode("utf-8")
    computed_digest = hmac.new(secret_bytes, raw_body_bytes, hashlib.sha256).hexdigest().lower()

    # Nettoyage de la signature reçue (suppression du préfixe sha256= si présent)
    received_sig = signature_header.strip().lower()
    if received_sig.startswith("sha256="):
        received_sig = received_sig[7:]

    return hmac.compare_digest(computed_digest, received_sig)


@transaction.atomic
def activate_pass_for_payment(payment):
    """
    Active le Pass Semestre de façon strictement idempotente pour un paiement validé.
    - Met à jour le statut APPROVED
    - Enregistre la date de paiement paid_at
    - Active / crée SemesterAccess
    - Active / crée UserSubscription V2 (180 jours)
    """
    if payment.status not in [Payment.STATUS_APPROVED, "reussi"]:
        payment.status = Payment.STATUS_APPROVED

    now = timezone.now()
    if not payment.paid_at:
        payment.paid_at = now

    semester = payment.semester
    if not semester and payment.semester_access:
        semester = payment.semester_access.semester

    if not semester:
        logger.error("[Chariow] Impossible d'activer le Pass : aucun semestre associé au paiement #%s", payment.id)
        payment.save()
        return False

    # 1. Activation SemesterAccess (Legacy)
    access, _ = SemesterAccess.objects.get_or_create(
        user=payment.user,
        semester=semester,
        defaults={
            "school": semester.filiere.school,
            "level": semester.filiere.level,
            "filiere": semester.filiere,
            "academic_year": semester.academic_year,
            "activated_at": now,
        }
    )

    if not access.activated_at:
        access.activated_at = now
        access.save()

    payment.semester_access = access
    payment.save()

    # 2. Activation UserSubscription V2 (durée 180 jours)
    sub, created = UserSubscription.objects.get_or_create(
        user=payment.user,
        semester=semester,
        defaults={
            "filiere": semester.filiere,
            "school": semester.filiere.school,
            "level": semester.filiere.level,
            "payment": payment,
            "start_date": now,
            "end_date": now + timedelta(days=180),
            "is_active": True,
        }
    )

    if not created:
        sub.is_active = True
        sub.payment = payment
        sub.end_date = now + timedelta(days=180)
        sub.save()

    logger.info(
        "[Chariow] Pass Semestre activé avec succès pour l'étudiant %s (Semestre: %s, Ref: %s)",
        payment.user.username, semester.label, payment.external_reference
    )
    return True


def handle_chariow_pulse_event(payload, delivery_id=None):
    """
    Traite un événement Pulse reçu de Chariow de façon sécurisée et idempotente.
    
    Événements pris en charge :
    - successful.sale : validation du paiement et activation du Pass
    - failed.sale : échec du paiement
    - abandoned.sale : abandon par l'étudiant
    - refunded.sale : remboursement
    """
    if not isinstance(payload, dict):
        return {"success": False, "error": "Payload invalide"}

    event_name = payload.get("event") or payload.get("type") or ""
    data = payload.get("data") or {}

    # Extraction des données de vente (structure plate ou imbriquée sous data.sale)
    sale_data = data.get("sale") if isinstance(data.get("sale"), dict) else data
    custom_metadata = (
        sale_data.get("custom_metadata") or
        data.get("custom_metadata") or
        payload.get("custom_metadata") or
        {}
    )

    # Récupération de la référence ArchivEx
    ext_ref = (
        custom_metadata.get("external_reference") or
        sale_data.get("external_reference") or
        data.get("external_reference")
    )

    payment_id = custom_metadata.get("archivex_payment_id")
    sale_id = sale_data.get("id") or data.get("id") or sale_data.get("sale_id")

    # Événements de vente pris en compte
    SALE_EVENTS = [
        "successful.sale", "sale.completed", "sale.success",
        "failed.sale", "sale.failed",
        "abandoned.sale", "sale.abandoned",
        "refunded.sale", "sale.refunded",
    ]

    # Si c'est un événement système, test ou non lié à une vente, acquitter avec 200 immédiatement
    if event_name and event_name not in SALE_EVENTS:
        logger.info("[Chariow Pulse] Événement ignoré (non bloquant) : %s", event_name)
        return {"success": True, "status": "ignored", "message": f"Événement {event_name} reçu."}

    # Recherche du paiement dans ArchivEx
    payment = None
    if ext_ref:
        payment = Payment.objects.filter(external_reference=ext_ref).first()
    if not payment and payment_id:
        payment = Payment.objects.filter(pk=payment_id).first()
    if not payment and sale_id:
        payment = Payment.objects.filter(chariow_sale_id=str(sale_id)).first()

    if not payment:
        logger.warning(
            "[Chariow Pulse] Aucun paiement trouvé pour ref=%s, payment_id=%s, sale_id=%s",
            ext_ref, payment_id, sale_id
        )
        return {"success": False, "error": "Paiement introuvable", "status_code": 404}


    # Association de l'ID de vente Chariow si disponible
    if sale_id and not payment.chariow_sale_id:
        payment.chariow_sale_id = str(sale_id)
        payment.save(update_fields=["chariow_sale_id"])

    # Traitement selon le type d'événement
    if event_name in ["successful.sale", "sale.completed", "sale.success"]:
        # Idempotence : si déjà validé, ne pas dupliquer
        if payment.is_approved:
            logger.info("[Chariow Pulse] Vente %s déjà traitée et validée.", payment.external_reference)
            return {"success": True, "status": "already_approved", "message": "Paiement déjà validé."}

        # Vérification optionnelle de conformité du montant
        sale_amount = sale_data.get("amount") or sale_data.get("total_amount") or sale_data.get("price")
        if sale_amount is not None:
            try:
                # Si le montant Chariow est fourni en centimes ou en entier
                numeric_amount = int(float(sale_amount))
                if numeric_amount > 0 and numeric_amount != int(payment.amount):
                    logger.warning(
                        "[Chariow Pulse] Différence de montant ref=%s : reçu=%s, attendu=%s",
                        payment.external_reference, numeric_amount, payment.amount
                    )
            except (ValueError, TypeError):
                pass

        payment.status = Payment.STATUS_APPROVED
        activate_pass_for_payment(payment)
        return {"success": True, "status": "approved", "message": "Pass Semestre activé avec succès."}

    elif event_name in ["failed.sale", "sale.failed"]:
        if not payment.is_approved:
            payment.status = Payment.STATUS_REJECTED
            payment.save(update_fields=["status"])
        logger.info("[Chariow Pulse] Échec de la vente ref=%s", payment.external_reference)
        return {"success": True, "status": "rejected", "message": "Paiement marqué comme échoué."}

    elif event_name in ["abandoned.sale", "sale.abandoned"]:
        if not payment.is_approved:
            payment.status = Payment.STATUS_CANCELLED
            payment.save(update_fields=["status"])
        logger.info("[Chariow Pulse] Vente abandonnée ref=%s", payment.external_reference)
        return {"success": True, "status": "abandoned", "message": "Paiement marqué comme abandonné."}

    elif event_name in ["refunded.sale", "sale.refunded"]:
        # Gestion du remboursement : désactivation de l'accès
        if payment.semester_access:
            payment.semester_access.activated_at = None
            payment.semester_access.save()
        UserSubscription.objects.filter(payment=payment).update(is_active=False)
        payment.status = Payment.STATUS_CANCELLED
        payment.save(update_fields=["status"])
        logger.info("[Chariow Pulse] Vente remboursée ref=%s", payment.external_reference)
        return {"success": True, "status": "refunded", "message": "Paiement remboursé et accès révoqué."}

    else:
        logger.info("[Chariow Pulse] Événement ignoré (non bloquant) : %s", event_name)
        return {"success": True, "status": "ignored", "message": f"Événement {event_name} reçu."}
