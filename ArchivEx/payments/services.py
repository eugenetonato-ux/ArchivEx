"""Client API SebPay (https://newapi.sebpay.bj/api/v1).

Paiement Mobile Money direct (Bénin : MTN & Moov).
SebPay envoie un prompt USSD/push sur le téléphone du client. Le client
valide le paiement sur son téléphone, puis SebPay notifie via webhook
et/ou l'utilisateur revient via return_url.

Contrat API réel (validé par sondage + doc officielle SebPay) :

  POST /collections
    Headers : X-Public-Key, X-Secret-Key, Content-Type: application/json
    Body    : {
        "amount": int,
        "currency": "XOF",
        "phone": "2290150196407",
        "operator": "mtn"|"moov",
        "country": "BJ",
        "external_reference": str,
    }

  GET /collections/{transaction_id}
    Réponse 200 : { "success": true, "data": { "status": "pending"|"completed"|"failed", ... } }

Module service synchrone : fonctions renvoyant des dicts.
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

# Pays par défaut (Bénin).
DEFAULT_COUNTRY = "BJ"

# Opérateurs autorisés : Moov et MTN uniquement.
OPERATOR_MTN = "mtn"
OPERATOR_MOOV = "moov"
SUPPORTED_OPERATORS = [OPERATOR_MTN, OPERATOR_MOOV]

# Table des indicatifs mobiles béninois -> opérateur, en vigueur depuis le
# 30/11/2024 (migration ARCEP vers la numérotation à 10 chiffres). TOUS les
# numéros béninois commencent désormais par le préfixe national fixe "01"
# (non discriminant), suivi de l'ancien indicatif à 2 chiffres qui, lui,
# détermine l'opérateur. Ex : 01 53 XX XX XX -> indicatif "53" -> MTN.
# Source : ARCEP-BENIN / notification UIT-T du 24/04/2024 (tableau 9.3).
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


def _headers():
    """Headers d'authentification requis par SebPay."""
    return {
        "X-Public-Key": getattr(settings, "SEBPAY_PUBLIC_KEY", ""),
        "X-Secret-Key": getattr(settings, "SEBPAY_SECRET_KEY", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def detect_operator(phone_input):
    """
    Détecte automatiquement l'opérateur béninois (mtn ou moov) à partir du numéro.
    Supporte les formats 8 chiffres, 10 chiffres (01XXXXXXXX) ou 13 chiffres (22901XXXXXXXX).
    Retourne 'mtn', 'moov' ou None si non reconnu.
    """
    if not phone_input:
        return None

    cleaned = re.sub(r"[^\d]", "", str(phone_input))

    if cleaned.startswith("00229"):
        cleaned = cleaned[5:]
    elif cleaned.startswith("229"):
        cleaned = cleaned[3:]

    # Si 10 chiffres commençant par 01 : indicatif aux positions [2:4]
    if len(cleaned) == 10 and cleaned.startswith("01"):
        indicator = cleaned[2:4]
        return _BJ_MOBILE_PREFIXES.get(indicator)

    # Si ancien format 8 chiffres : indicatif aux positions [0:2]
    if len(cleaned) == 8:
        indicator = cleaned[0:2]
        return _BJ_MOBILE_PREFIXES.get(indicator)

    return None


def normalize_benin_phone(phone_input):
    """
    Normalise un numéro de téléphone béninois au format officiel SebPay (22901XXXXXXXX - 13 chiffres).
    Exemples acceptés :
      - '0150196407' -> '2290150196407'
      - '50196407' -> '2290150196407'
      - '+229 01 50 19 64 07' -> '2290150196407'
      - '2290150196407' -> '2290150196407'
    """
    if not phone_input:
        raise ValueError("Le numéro de téléphone est obligatoire.")

    cleaned = re.sub(r"[^\d]", "", str(phone_input))

    if cleaned.startswith("00229"):
        cleaned = cleaned[5:]
    elif cleaned.startswith("229"):
        cleaned = cleaned[3:]

    # Si l'étudiant a saisi l'ancien format 8 chiffres (ex: 50196407), ajout automatique du préfixe national 01
    if len(cleaned) == 8:
        cleaned = f"01{cleaned}"

    # Vérification du format 10 chiffres national Bénin (01XXXXXXXX)
    if len(cleaned) != 10 or not cleaned.startswith("01"):
        raise ValueError(
            "Numéro béninois invalide. Exemple attendu : 01 50 19 64 07 ou 50 19 64 07."
        )

    return f"229{cleaned}"


def generate_external_reference():
    """Génère une référence unique pour SebPay (ex: ARCHIVEX-PASS-2026-A1B2C3)."""
    year = timezone.now().year
    code = uuid.uuid4().hex[:6].upper()
    ref = f"ARCHIVEX-PASS-{year}-{code}"
    while Payment.objects.filter(external_reference=ref).exists():
        code = uuid.uuid4().hex[:6].upper()
        ref = f"ARCHIVEX-PASS-{year}-{code}"
    return ref


def create_sebpay_collection(payment, callback_url=None):
    """
    Envoie une requête d'encaissement Mobile Money à l'API SebPay.
    POST https://newapi.sebpay.bj/api/v1/collections
    """
    base_url = getattr(settings, "SEBPAY_BASE_URL", "https://newapi.sebpay.bj/api/v1").rstrip("/")
    url = f"{base_url}/collections"

    # Vérification de l'opérateur (mtn ou moov uniquement)
    op = (payment.operator or "").lower().strip()
    if op not in SUPPORTED_OPERATORS:
        detected = detect_operator(payment.phone_number)
        op = detected if detected in SUPPORTED_OPERATORS else OPERATOR_MTN

    payload = {
        "amount": int(payment.amount),
        "currency": payment.currency or getattr(settings, "SEBPAY_CURRENCY", "XOF"),
        "phone": payment.phone_number,
        "operator": op,
        "country": getattr(settings, "SEBPAY_COUNTRY", DEFAULT_COUNTRY),
        "external_reference": payment.external_reference,
    }

    cb_url = callback_url or getattr(settings, "SEBPAY_CALLBACK_URL", None)
    if cb_url:
        payload["callback_url"] = cb_url

    headers = _headers()

    try:
        logger.info("[SebPay] Envoi collection ref=%s, montant=%s, phone=%s, op=%s",
                    payment.external_reference, payment.amount, payment.phone_number, op)
        response = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        
        try:
            res_data = response.json()
        except Exception:
            res_data = {"raw": response.text}

        if response.status_code in [200, 201]:
            data_body = res_data.get("data", res_data)
            sebpay_id = (
                data_body.get("id") or
                data_body.get("transaction_id") or
                data_body.get("reference") or
                res_data.get("transaction_id") or
                res_data.get("id")
            )
            if sebpay_id:
                payment.sebpay_transaction_id = str(sebpay_id)
                payment.save(update_fields=["sebpay_transaction_id"])
            return {"success": True, "data": res_data}

        logger.warning("[SebPay] Échec collection HTTP %s: %s", response.status_code, res_data)
        return {
            "success": False,
            "error": res_data.get("message") or res_data.get("error") or f"Erreur SebPay HTTP {response.status_code}",
            "data": res_data,
        }
    except requests.exceptions.RequestException as e:
        logger.error("[SebPay] Exception requête collection: %s", e)
        return {"success": False, "error": f"Erreur de connexion SebPay : {str(e)}"}


def verify_sebpay_transaction(reference_or_id):
    """
    Vérifie le statut d'une transaction auprès de SebPay.
    GET https://newapi.sebpay.bj/api/v1/collections/{transaction_id}
    """
    if not reference_or_id:
        return {"success": False, "error": "Identifiant de transaction manquant."}

    base_url = getattr(settings, "SEBPAY_BASE_URL", "https://newapi.sebpay.bj/api/v1").rstrip("/")
    url = f"{base_url}/collections/{reference_or_id}"
    headers = _headers()

    try:
        response = requests.get(url, headers=headers, timeout=_TIMEOUT)
        try:
            res_data = response.json()
        except Exception:
            res_data = {"raw": response.text}

        if response.status_code == 200:
            return {"success": True, "data": res_data.get("data", res_data)}

        logger.warning("[SebPay] Échec vérification transaction HTTP %s: %s", response.status_code, res_data)
        return {"success": False, "error": res_data.get("message") or f"Erreur HTTP {response.status_code}"}
    except requests.exceptions.RequestException as e:
        logger.error("[SebPay] Exception vérification transaction: %s", e)
        return {"success": False, "error": str(e)}


def verify_webhook_signature(raw_body, signature_header):
    """
    Vérifie la signature HMAC-SHA256 transmise dans le header X-SebPay-Signature.
    """
    if not signature_header or not raw_body:
        return False

    secret_key = getattr(settings, "SEBPAY_SECRET_KEY", "").encode("utf-8")
    if isinstance(raw_body, str):
        raw_body_bytes = raw_body.encode("utf-8")
    else:
        raw_body_bytes = raw_body

    expected_sig = hmac.new(secret_key, raw_body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig.lower(), signature_header.strip().lower())


@transaction.atomic
def activate_pass_for_payment(payment):
    """
    Active le Pass Semestre de façon strictement idempotente pour un paiement APPROVED.
    - Active / crée SemesterAccess
    - Active / crée UserSubscription V2
    - Enregistre la date de paiement
    """
    if payment.status not in [Payment.STATUS_APPROVED, "reussi"]:
        return False

    now = timezone.now()
    if not payment.paid_at:
        payment.paid_at = now

    semester = payment.semester
    if not semester and payment.semester_access:
        semester = payment.semester_access.semester

    if not semester:
        return False

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

    # Créer / Activer l'abonnement V2 idempotemment pour 1 semestre (180 jours)
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

    if not created and not sub.is_active:
        sub.is_active = True
        sub.end_date = now + timedelta(days=180)
        sub.save()

    return True
