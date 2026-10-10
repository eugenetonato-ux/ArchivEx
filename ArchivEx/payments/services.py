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
OPERATOR_CELTIIS = "celtiis"
SUPPORTED_OPERATORS = [OPERATOR_MTN, OPERATOR_MOOV, OPERATOR_CELTIIS]

# Indicatifs mobiles béninois (ARCEP 10 chiffres / 8 chiffres)
_BJ_MOBILE_PREFIXES = {
    # MTN Bénin
    "42": OPERATOR_MTN, "46": OPERATOR_MTN, "50": OPERATOR_MTN, "51": OPERATOR_MTN,
    "52": OPERATOR_MTN, "53": OPERATOR_MTN, "54": OPERATOR_MTN, "56": OPERATOR_MTN,
    "57": OPERATOR_MTN, "59": OPERATOR_MTN, "61": OPERATOR_MTN, "62": OPERATOR_MTN,
    "66": OPERATOR_MTN, "67": OPERATOR_MTN, "69": OPERATOR_MTN, "90": OPERATOR_MTN,
    "91": OPERATOR_MTN, "96": OPERATOR_MTN, "97": OPERATOR_MTN,
    # Moov Bénin
    "45": OPERATOR_MOOV, "55": OPERATOR_MOOV, "58": OPERATOR_MOOV, "60": OPERATOR_MOOV,
    "63": OPERATOR_MOOV, "64": OPERATOR_MOOV, "65": OPERATOR_MOOV, "68": OPERATOR_MOOV,
    "94": OPERATOR_MOOV, "95": OPERATOR_MOOV, "98": OPERATOR_MOOV, "99": OPERATOR_MOOV,
    # Celtiis Bénin
    "40": OPERATOR_CELTIIS, "41": OPERATOR_CELTIIS, "43": OPERATOR_CELTIIS,
    "44": OPERATOR_CELTIIS, "49": OPERATOR_CELTIIS, "92": OPERATOR_CELTIIS,
    "93": OPERATOR_CELTIIS,
}


def get_fedapay_base_url():
    """
    Retourne l'URL de base de l'API FedaPay selon l'environnement configuré.
    - 'sandbox' : https://sandbox-api.fedapay.com/v1
    - 'live' : https://api.fedapay.com/v1
    """
    env = getattr(settings, "FEDAPAY_ENVIRONMENT", "sandbox").strip().lower()
    if env in ["live", "production"]:
        return "https://api.fedapay.com/v1"
    return "https://sandbox-api.fedapay.com/v1"


def _fedapay_headers():
    """Génère les en-têtes d'authentification pour l'API FedaPay."""
    api_key = getattr(settings, "FEDAPAY_SECRET_KEY", "").strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _chariow_headers():
    """Génère les headers d'authentification pour l'API Chariow (legacy)."""
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


def create_fedapay_transaction(payment, callback_url=None):
    """
    Initialise une transaction sur la passerelle FedaPay (https://fedapay.com).
    Processus conforme à la documentation officielle FedaPay :
    1. POST /v1/transactions (création de l'objet transaction avec montant, devise, client, métadonnées)
    2. POST /v1/transactions/{id}/token (génération du token et de l'URL sécurisée de checkout)

    Met à jour l'enregistrement Payment avec :
    - payment.fedapay_transaction_id
    - payment.fedapay_checkout_url
    """
    secret_key = getattr(settings, "FEDAPAY_SECRET_KEY", "").strip()
    if not secret_key:
        logger.error("[FedaPay] FEDAPAY_SECRET_KEY non configurée dans settings / .env.")
        return {
            "success": False,
            "error": "Le service de paiement est temporairement indisponible (clé API FedaPay non configurée).",
        }

    user = payment.user
    email = getattr(user, "email", None) or f"{user.username}@archivex.bj"
    raw_first = (getattr(user, "first_name", "") or "").strip()
    raw_last = (getattr(user, "last_name", "") or "").strip()

    if not raw_last:
        if " " in raw_first:
            first_name, last_name = raw_first.split(" ", 1)
        elif " " in (user.username or ""):
            first_name, last_name = user.username.split(" ", 1)
        else:
            first_name = raw_first or user.username or "Étudiant"
            last_name = "ArchivEx"
    else:
        first_name = raw_first or user.username or "Étudiant"
        last_name = raw_last

    # Normalisation du numéro national (10 chiffres)
    phone_digits = re.sub(r"[^\d]", "", str(payment.phone_number or ""))
    if phone_digits.startswith("229") and len(phone_digits) == 13:
        national_number = phone_digits[3:]
    else:
        national_number = phone_digits

    base_url = get_fedapay_base_url()
    headers = _fedapay_headers()
    currency_iso = getattr(settings, "FEDAPAY_CURRENCY", "XOF")
    semester_label = payment.semester.label if payment.semester else "Pass Semestre"

    # Construction du payload transactionnel
    tx_payload = {
        "description": f"Pass Semestre ArchivEx - {semester_label}",
        "amount": int(payment.amount),
        "currency": {"iso": currency_iso},
        "callback_url": callback_url or "",
        "customer": {
            "firstname": first_name,
            "lastname": last_name,
            "email": email,
            "phone_number": {
                "number": national_number or "0100000000",
                "country": "bj",
            }
        },
        "custom_metadata": {
            "external_reference": payment.external_reference,
            "archivex_payment_id": str(payment.id),
            "archivex_user_id": str(user.id),
            "archivex_semester_id": str(payment.semester_id) if payment.semester_id else "",
            "plan": "semester_pass",
        }
    }

    try:
        logger.info(
            "[FedaPay] Création transaction ref=%s, montant=%s %s, user=%s (base_url=%s)",
            payment.external_reference, payment.amount, currency_iso, user.username, base_url
        )

        # 1. Création de la transaction
        create_url = f"{base_url}/transactions"
        tx_res = requests.post(create_url, json=tx_payload, headers=headers, timeout=_TIMEOUT)

        try:
            tx_data = tx_res.json()
        except Exception:
            tx_data = {"raw": tx_res.text}

        if tx_res.status_code not in [200, 201]:
            error_msg = (
                tx_data.get("message") or
                tx_data.get("error") or
                tx_data.get("errors") or
                f"Erreur API FedaPay (HTTP {tx_res.status_code})"
            )
            logger.warning("[FedaPay] Échec création transaction : %s", error_msg)
            return {"success": False, "error": str(error_msg), "status_code": tx_res.status_code}

        # Extraction de l'ID de la transaction créée
        tx_obj = (
            tx_data.get("v1/transaction") or
            tx_data.get("transaction") or
            tx_data.get("data") or
            tx_data
        )
        tx_id = tx_obj.get("id") if isinstance(tx_obj, dict) else None

        if not tx_id:
            logger.error("[FedaPay] ID de transaction manquant dans la réponse: %s", tx_data)
            return {"success": False, "error": "Identifiant de transaction introuvable dans la réponse FedaPay."}

        # 2. Génération du token / URL de paiement FedaPay
        token_url = f"{base_url}/transactions/{tx_id}/token"
        token_res = requests.post(token_url, json={}, headers=headers, timeout=_TIMEOUT)

        try:
            token_data = token_res.json()
        except Exception:
            token_data = {"raw": token_res.text}

        if token_res.status_code not in [200, 201]:
            error_msg = token_data.get("message") or f"Erreur génération du lien FedaPay (HTTP {token_res.status_code})"
            logger.warning("[FedaPay] Échec génération token pour tx #%s : %s", tx_id, error_msg)
            return {"success": False, "error": str(error_msg), "status_code": token_res.status_code}

        checkout_url = (
            token_data.get("url") or
            (token_data.get("token", {}).get("url") if isinstance(token_data.get("token"), dict) else None)
        )

        if not checkout_url and token_data.get("token") and isinstance(token_data.get("token"), str):
            checkout_url = f"https://checkout.fedapay.com/token/{token_data['token']}"

        # Persistance locale dans Payment
        payment.fedapay_transaction_id = str(tx_id)
        if checkout_url:
            payment.fedapay_checkout_url = checkout_url
        payment.save(update_fields=["fedapay_transaction_id", "fedapay_checkout_url"])

        logger.info(
            "[FedaPay] Checkout généré avec succès pour ref=%s (tx_id=%s, url=%s)",
            payment.external_reference, tx_id, checkout_url
        )

        return {
            "success": True,
            "transaction_id": tx_id,
            "checkout_url": checkout_url,
            "data": token_data,
        }

    except requests.exceptions.Timeout:
        logger.error("[FedaPay] Timeout lors de l'appel FedaPay pour ref=%s", payment.external_reference)
        return {"success": False, "error": "Le service FedaPay n'a pas répondu à temps. Veuillez réessayer."}
    except requests.exceptions.RequestException as e:
        logger.error("[FedaPay] Exception de connexion lors de l'appel FedaPay : %s", e)
        return {"success": False, "error": "Erreur de communication avec la plateforme de paiement FedaPay."}


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
    raw_first = (getattr(user, "first_name", "") or "").strip()
    raw_last = (getattr(user, "last_name", "") or "").strip()

    if not raw_last:
        if " " in raw_first:
            first_name, last_name = raw_first.split(" ", 1)
        elif " " in (user.username or ""):
            first_name, last_name = user.username.split(" ", 1)
        else:
            first_name = raw_first or user.username or "Étudiant"
            last_name = "ArchivEx"
    else:
        first_name = raw_first or user.username or "Étudiant"
        last_name = raw_last

    # Nettoyage du numéro pour l'objet phone
    phone_digits = re.sub(r"[^\d]", "", str(payment.phone_number or ""))
    # Si le numéro commence par l'indicatif 229, on extrait les 10 chiffres nationaux
    if phone_digits.startswith("229") and len(phone_digits) == 13:
        national_number = phone_digits[3:]
    else:
        national_number = phone_digits

    final_redirect_url = redirect_url or ""
    if final_redirect_url and "{sale_id}" not in final_redirect_url:
        separator = "&" if "?" in final_redirect_url else "?"
        final_redirect_url = f"{final_redirect_url}{separator}sale_id={{sale_id}}"

    payload = {
        "product_id": product_id,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "redirect_url": final_redirect_url,
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


def verify_fedapay_webhook_signature(raw_body, signature_header):
    """
    Vérifie la signature HMAC-SHA256 du webhook FedaPay transmise dans l'en-tête 'X-FEDAPAY-SIGNATURE'.
    Selon la documentation FedaPay :
    - L'en-tête contient soit direct '<signature_hex>', soit 's=<signature_hex>',
      ou au format horodaté 't=<timestamp>,s=<signature_hex>', ou 'v1=<signature_hex>'.
    - La signature est calculée avec la clé secrète de l'endpoint webhook (FEDAPAY_WEBHOOK_SECRET)
      ou fallback sur la clé secrète API (FEDAPAY_SECRET_KEY).
    """
    if not signature_header or not raw_body:
        return False

    webhook_secret = getattr(settings, "FEDAPAY_WEBHOOK_SECRET", "").strip()
    api_secret = getattr(settings, "FEDAPAY_SECRET_KEY", "").strip()
    candidate_secrets = [s for s in [webhook_secret, api_secret] if s]

    if not candidate_secrets:
        return False

    if isinstance(raw_body, str):
        raw_body_bytes = raw_body.encode("utf-8")
    else:
        raw_body_bytes = raw_body

    sig_str = signature_header.strip()

    # Extraction des paires clé=valeur si présentes (t=..., s=..., v1=...)
    parts = dict(re.findall(r"([a-zA-Z0-9_]+)=([^,]+)", sig_str))
    candidate_signatures = []

    for key in ["s", "v1", "sig"]:
        if key in parts:
            candidate_signatures.append(parts[key].strip().lower())

    candidate_signatures.append(sig_str.lower())
    if sig_str.startswith("sha256="):
        candidate_signatures.append(sig_str[7:].lower())

    timestamp = parts.get("t")

    for sec in candidate_secrets:
        sec_bytes = sec.encode("utf-8")

        # 1. Vérification avec horodatage (timestamp.payload)
        if timestamp:
            signed_payload = f"{timestamp}.".encode("utf-8") + raw_body_bytes
            computed = hmac.new(sec_bytes, signed_payload, hashlib.sha256).hexdigest().lower()
            for cand in candidate_signatures:
                if hmac.compare_digest(computed, cand):
                    return True

        # 2. Vérification directe sur le corps brut (standard HMAC-SHA256)
        computed_direct = hmac.new(sec_bytes, raw_body_bytes, hashlib.sha256).hexdigest().lower()
        for cand in candidate_signatures:
            if hmac.compare_digest(computed_direct, cand):
                return True

    return False


def create_payment_notification(payment):
    """Crée une notification in-app dans le centre de notifications de l'étudiant."""
    try:
        from notifications.models import Notification
        from django.urls import reverse

        user = payment.user
        semester = payment.semester
        sem_label = semester.label if semester else "Semestre"
        filiere_name = semester.filiere.name if (semester and semester.filiere) else ""
        link = reverse("academics:matieres", kwargs={"semester_id": semester.id}) if semester else reverse("accounts:dashboard")

        title = f"Pass {sem_label} activé avec succès !"
        message = (
            f"Votre règlement de {payment.amount} {payment.currency} a été validé. "
            f"L'intégralité des épreuves, corrigés détaillés et résumés de {sem_label} "
            f"({filiere_name}) est désormais débloquée."
        )

        existing = Notification.objects.filter(recipient=user, title=title).first()
        if not existing:
            Notification.objects.create(
                recipient=user,
                notification_type="PAYMENT",
                title=title,
                message=message,
                link=link,
                is_read=False,
            )
            logger.info("[Notif Pass] Notification in-app créée pour %s", user.username)
        return True
    except Exception as e:
        logger.error("[Notif Pass] Erreur lors de la création de la notification : %s", e)
        return False


def send_payment_confirmation_email(payment):
    """Envoie un email HTML transactionnel de confirmation de commande et d'activation du Pass."""
    try:
        user = payment.user
        recipient_email = user.email
        if not recipient_email or "@" not in recipient_email:
            logger.warning("[Email Pass] Utilisateur %s sans adresse email valide.", user.username)
            return False

        semester = payment.semester
        sem_label = semester.label if semester else "Semestre"
        filiere_name = semester.filiere.name if (semester and semester.filiere) else ""
        school_name = semester.filiere.school.name if (semester and semester.filiere and semester.filiere.school) else "Université"

        subject = f"[ArchivEx] Confirmation d'activation — Pass {sem_label} ({payment.external_reference})"

        html_message = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #F8FAFC; margin: 0; padding: 20px; color: #1E293B; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #FFFFFF; border-radius: 20px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #E2E8F0; }}
  .header {{ background: linear-gradient(135deg, #071A49 0%, #0E2461 50%, #1D4ED8 100%); padding: 36px 30px; text-align: center; color: #FFFFFF; }}
  .header h1 {{ margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.5px; }}
  .header p {{ margin: 8px 0 0 0; color: #BFDBFE; font-size: 13px; font-weight: 500; }}
  .content {{ padding: 32px 30px; }}
  .badge {{ display: inline-block; background-color: #DCFCE7; color: #166534; font-size: 12px; font-weight: 800; padding: 6px 14px; border-radius: 9999px; text-transform: uppercase; margin-bottom: 16px; }}
  .title {{ font-size: 20px; font-weight: 800; color: #071A49; margin-bottom: 12px; }}
  .text {{ font-size: 14px; line-height: 1.6; color: #475569; margin-bottom: 24px; }}
  .details-box {{ background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 16px; padding: 20px; margin-bottom: 28px; }}
  .detail-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px dashed #CBD5E1; font-size: 13px; }}
  .detail-row:last-child {{ border-bottom: none; }}
  .detail-label {{ color: #64748B; }}
  .detail-value {{ font-weight: 700; color: #071A49; text-align: right; }}
  .btn {{ display: block; text-align: center; background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%); color: #FFFFFF !important; text-decoration: none; padding: 14px 28px; border-radius: 14px; font-weight: 800; font-size: 14px; box-shadow: 0 4px 12px rgba(37,99,235,0.3); margin: 24px 0; }}
  .footer {{ background-color: #F1F5F9; padding: 20px 30px; text-align: center; font-size: 12px; color: #64748B; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>ArchivEx</h1>
    <p>La référence universitaire des étudiants d'excellence</p>
  </div>
  <div class="content">
    <div class="badge">Paiement Confirmé</div>
    <div class="title">Votre Pass Semestre est actif !</div>
    <p class="text">
      Bonjour <strong>{user.first_name or user.username}</strong>,<br><br>
      Nous vous confirmons la validation de votre règlement pour votre <strong>Pass {sem_label}</strong>.
      Vos accès sont immédiatement actifs sur votre compte ArchivEx. Vous pouvez dès à présent consulter toutes les épreuves, corrigés détaillés et résumés de cours.
    </p>
    <div class="details-box">
      <div class="detail-row">
        <span class="detail-label">Référence :</span>
        <span class="detail-value">{payment.external_reference}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Semestre débloqué :</span>
        <span class="detail-value">{sem_label}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Filière / École :</span>
        <span class="detail-value">{filiere_name} ({school_name})</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Montant réglé :</span>
        <span class="detail-value">{payment.amount} {payment.currency}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Date d'activation :</span>
        <span class="detail-value">{timezone.now().strftime('%d/%m/%Y à %H:%M')}</span>
      </div>
    </div>
    <a href="https://archivex.online/academics/semestre/{semester.id}/matieres/" class="btn">
      Accéder à mes épreuves et corrigés →
    </a>
    <p class="text" style="font-size: 12px; color: #94A3B8; margin-top: 16px;">
      Si vous avez des questions ou besoin d'assistance, notre équipe est disponible via la rubrique Support sur le site ou par email à digitalarchivex@gmail.com.
    </p>
  </div>
  <div class="footer">
    © 2026 ArchivEx — Tous droits réservés.
  </div>
</div>
</body>
</html>"""

        plain_message = (
            f"Bonjour {user.first_name or user.username},\n\n"
            f"Votre Pass Semestre {sem_label} sur ArchivEx est désormais actif !\n"
            f"Référence : {payment.external_reference}\n"
            f"Montant : {payment.amount} {payment.currency}\n\n"
            f"Accédez à vos cours et épreuves : https://archivex.online/academics/semestre/{semester.id}/matieres/\n\n"
            f"L'équipe ArchivEx"
        )

        from django.core.mail import send_mail
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "digitalarchivex@gmail.com"),
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info("[Email Pass] Email de confirmation envoyé avec succès à %s", recipient_email)
        return True
    except Exception as e:
        logger.error("[Email Pass] Erreur lors de l'envoi de l'email de confirmation : %s", e)
        return False


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
    - Active / crée SemesterAccess avec gestion robuste des clés étrangères nulles
    - Active / crée UserSubscription V2 (180 jours)
    - Déclenche la notification in-app
    - Envoie l'email transactionnel de confirmation
    """
    from academics.models import AcademicYear, School, Level, Filiere, Semester

    if payment.status not in [Payment.STATUS_APPROVED, "reussi"]:
        payment.status = Payment.STATUS_APPROVED

    now = timezone.now()
    if not payment.paid_at:
        payment.paid_at = now

    semester = payment.semester
    if not semester and payment.semester_access:
        semester = payment.semester_access.semester

    if not semester:
        semester = Semester.objects.filter(is_active=True).first()

    user_prof = getattr(payment.user, "profile", None)
    school = None
    level = None
    filiere = None

    if semester and semester.filiere:
        filiere = semester.filiere
        school = semester.filiere.school
        level = semester.filiere.level
    elif user_prof:
        school = user_prof.school
        level = user_prof.level
        filiere = user_prof.filiere

    if not school:
        school = School.objects.first()
    if not level:
        level = Level.objects.first()
    if not filiere:
        filiere = Filiere.objects.first()

    academic_year = (semester.academic_year if semester else None) or AcademicYear.objects.order_by("-label").first()

    if semester and not semester.academic_year and academic_year:
        try:
            semester.academic_year = academic_year
            semester.save(update_fields=["academic_year"])
        except Exception:
            pass

    # 1. Activation SemesterAccess (Legacy & Central)
    access = SemesterAccess.objects.filter(user=payment.user, semester=semester).first()
    if not access:
        access = SemesterAccess.objects.create(
            user=payment.user,
            semester=semester,
            school=school,
            level=level,
            filiere=filiere,
            academic_year=academic_year,
            activated_at=now,
        )
    else:
        if not access.activated_at:
            access.activated_at = now
        if not access.academic_year and academic_year:
            access.academic_year = academic_year
        if not access.school and school:
            access.school = school
        if not access.level and level:
            access.level = level
        if not access.filiere and filiere:
            access.filiere = filiere
        access.save()

    payment.semester = semester
    payment.semester_access = access
    payment.save()

    # 2. Activation UserSubscription V2 (durée 180 jours)
    sub = UserSubscription.objects.filter(user=payment.user, semester=semester).first()
    if not sub:
        sub = UserSubscription.objects.create(
            user=payment.user,
            semester=semester,
            filiere=filiere,
            school=school,
            level=level,
            payment=payment,
            start_date=now,
            end_date=now + timedelta(days=180),
            is_active=True,
        )
    else:
        sub.is_active = True
        sub.payment = payment
        sub.start_date = now
        sub.end_date = now + timedelta(days=180)
        sub.save()

    logger.info(
        "[Pass Semestre] Activé avec succès pour l'étudiant %s (Semestre: %s, Ref: %s)",
        payment.user.username, getattr(semester, "label", "N/A"), payment.external_reference
    )

    # 3. Notification In-App
    try:
        create_payment_notification(payment)
    except Exception as e:
        logger.error("[Pass Semestre] Erreur lors de la notification in-app : %s", e)

    # 4. Email Transactionnel
    try:
        send_payment_confirmation_email(payment)
    except Exception as e:
        logger.error("[Pass Semestre] Erreur lors de l'envoi de l'email : %s", e)

    return True


def verify_and_sync_fedapay_transaction(payment, transaction_id=None):
    """
    Interroge l'API FedaPay en direct (GET /v1/transactions/{id}) pour vérifier l'état réel de la transaction
    et synchroniser le statut du paiement local.
    Permet une validation immédiate et résiliente même en l'absence ou retard de webhook.
    """
    if payment.is_approved:
        return {"success": True, "status": "already_approved", "is_approved": True}

    target_id = transaction_id or payment.fedapay_transaction_id
    if not target_id:
        return {
            "success": False,
            "status": payment.status,
            "is_approved": False,
            "message": "Aucun identifiant de transaction FedaPay disponible pour la synchronisation.",
        }

    base_url = get_fedapay_base_url()
    headers = _fedapay_headers()

    try:
        url = f"{base_url}/transactions/{target_id}"
        res = requests.get(url, headers=headers, timeout=_TIMEOUT)

        if res.status_code != 200:
            logger.warning("[FedaPay Sync] Erreur HTTP %s lors de la récupération de la transaction #%s", res.status_code, target_id)
            return {"success": False, "status": payment.status, "is_approved": False}

        data = res.json()
        tx = (
            data.get("v1/transaction") or
            data.get("transaction") or
            data.get("data") or
            data
        )

        status = (tx.get("status") or "").lower()
        actual_id = tx.get("id") or target_id

        # Vérification de sécurité absolue : la transaction FedaPay DOIT correspondre à ce paiement précis
        tx_meta = tx.get("custom_metadata") or {}
        tx_ref = tx_meta.get("external_reference") or tx.get("reference") or tx.get("external_reference")
        tx_pay_id = tx_meta.get("archivex_payment_id")

        matches_ref = bool(tx_ref and str(tx_ref).strip() == str(payment.external_reference).strip())
        matches_pay_id = bool(tx_pay_id and str(tx_pay_id).strip() == str(payment.id).strip())
        matches_tx_id = bool(payment.fedapay_transaction_id and str(payment.fedapay_transaction_id).strip() == str(actual_id).strip())

        if not (matches_ref or matches_pay_id or matches_tx_id):
            logger.critical(
                "[Security Alert] Tentative de validation de paiement avec une transaction FedaPay non concordante ! "
                "payment_ref=%s, user=%s, attempted_tx_id=%s",
                payment.external_reference, payment.user_id, actual_id
            )
            return {"success": False, "status": payment.status, "is_approved": False, "error": "Transaction non concordante."}

        # Vérification stricte du montant payé
        tx_amount = tx.get("amount")
        if tx_amount is not None:
            try:
                if int(float(tx_amount)) < int(float(payment.amount)):
                    logger.critical(
                        "[Security Alert] Montant de transaction FedaPay inférieur au montant requis ! "
                        "reçu=%s, attendu=%s pour ref=%s",
                        tx_amount, payment.amount, payment.external_reference
                    )
                    return {"success": False, "status": payment.status, "is_approved": False, "error": "Montant invalide."}
            except (ValueError, TypeError):
                pass

        if actual_id and not payment.fedapay_transaction_id:
            payment.fedapay_transaction_id = str(actual_id)
            payment.save(update_fields=["fedapay_transaction_id"])

        if status in ["approved", "transferred"]:
            payment.status = Payment.STATUS_APPROVED
            payment.save(update_fields=["status"])
            activate_pass_for_payment(payment)
            logger.info(
                "[FedaPay Sync] Paiement %s validé avec succès via l'API FedaPay (tx_id=%s)",
                payment.external_reference, actual_id
            )
            return {
                "success": True,
                "status": "approved",
                "is_approved": True,
                "transaction_id": actual_id,
                "message": "Pass Semestre activé avec succès.",
            }

        elif status in ["declined"]:
            payment.status = Payment.STATUS_REJECTED
            payment.save(update_fields=["status"])
            return {
                "success": True,
                "status": "rejected",
                "is_approved": False,
                "transaction_id": actual_id,
                "message": "Paiement décliné par FedaPay.",
            }

        elif status in ["canceled", "cancelled"]:
            payment.status = Payment.STATUS_CANCELLED
            payment.save(update_fields=["status"])
            return {
                "success": True,
                "status": "cancelled",
                "is_approved": False,
                "transaction_id": actual_id,
                "message": "Transaction annulée par l'utilisateur.",
            }

        return {
            "success": True,
            "status": payment.status,
            "is_approved": False,
            "transaction_id": actual_id,
            "message": f"Transaction FedaPay en cours (statut: {status}).",
        }

    except requests.exceptions.RequestException as e:
        logger.warning("[FedaPay Sync] Erreur lors de la synchronisation de la transaction #%s : %s", target_id, e)
        return {"success": False, "status": payment.status, "is_approved": False, "error": str(e)}


def handle_fedapay_webhook_event(payload):
    """
    Traite un événement Webhook reçu de FedaPay de façon sécurisée et idempotente.
    Structure FedaPay :
    - 'name' / 'event' : 'transaction.approved', 'transaction.declined', 'transaction.canceled', etc.
    - 'entity' : objet transaction contenant id, status, amount, custom_metadata...
    """
    if not isinstance(payload, dict):
        return {"success": False, "error": "Payload JSON invalide"}

    event_name = (payload.get("name") or payload.get("event") or payload.get("type") or "").lower()
    entity = payload.get("entity") or payload.get("data") or {}

    custom_metadata = entity.get("custom_metadata") or {}
    ext_ref = (
        custom_metadata.get("external_reference") or
        entity.get("reference") or
        entity.get("external_reference")
    )
    payment_id = custom_metadata.get("archivex_payment_id")
    tx_id = entity.get("id")

    # Événements traités
    FEDAPAY_EVENTS = [
        "transaction.approved", "transaction.transferred",
        "transaction.declined", "transaction.canceled", "transaction.cancelled",
        "transaction.created",
    ]

    if event_name and event_name not in FEDAPAY_EVENTS:
        logger.info("[FedaPay Webhook] Événement ignoré (non bloquant) : %s", event_name)
        return {"success": True, "status": "ignored", "message": f"Événement {event_name} reçu."}

    # Recherche du paiement correspondant
    payment = None
    if ext_ref:
        payment = Payment.objects.filter(external_reference=ext_ref).first()
    if not payment and payment_id:
        payment = Payment.objects.filter(pk=payment_id).first()
    if not payment and tx_id:
        payment = Payment.objects.filter(fedapay_transaction_id=str(tx_id)).first()

    if not payment:
        logger.warning(
            "[FedaPay Webhook] Aucun paiement trouvé pour ref=%s, payment_id=%s, tx_id=%s",
            ext_ref, payment_id, tx_id
        )
        return {"success": False, "error": "Paiement introuvable", "status_code": 404}

    if tx_id and not payment.fedapay_transaction_id:
        payment.fedapay_transaction_id = str(tx_id)
        payment.save(update_fields=["fedapay_transaction_id"])

    # Traitement selon l'événement
    if event_name in ["transaction.approved", "transaction.transferred"]:
        if payment.is_approved:
            logger.info("[FedaPay Webhook] Transaction %s déjà validée.", payment.external_reference)
            return {"success": True, "status": "already_approved", "message": "Paiement déjà validé."}

        payment.status = Payment.STATUS_APPROVED
        payment.save(update_fields=["status"])
        activate_pass_for_payment(payment)
        logger.info("[FedaPay Webhook] Paiement %s validé avec succès !", payment.external_reference)
        return {"success": True, "status": "approved", "message": "Pass Semestre activé avec succès."}

    elif event_name in ["transaction.declined"]:
        if not payment.is_approved:
            payment.status = Payment.STATUS_REJECTED
            payment.save(update_fields=["status"])
        logger.info("[FedaPay Webhook] Transaction déclinée pour %s", payment.external_reference)
        return {"success": True, "status": "rejected", "message": "Paiement marqué comme décliné."}

    elif event_name in ["transaction.canceled", "transaction.cancelled"]:
        if not payment.is_approved:
            payment.status = Payment.STATUS_CANCELLED
            payment.save(update_fields=["status"])
        logger.info("[FedaPay Webhook] Transaction annulée pour %s", payment.external_reference)
        return {"success": True, "status": "cancelled", "message": "Paiement marqué comme annulé."}

    return {"success": True, "status": "acknowledged", "message": f"Événement {event_name} reçu."}


def verify_and_sync_chariow_sale(payment, sale_id=None):
    """
    Interroge l'API Chariow en direct pour vérifier l'état réel d'une transaction et synchroniser le paiement local.
    Garantit une validation immédiate et résiliente même si le webhook Pulse est désactivé ou retardé.
    """
    if payment.is_approved:
        return {"success": True, "status": "already_approved", "is_approved": True}

    target_sale_id = sale_id or payment.chariow_sale_id or None
    base_url = getattr(settings, "CHARIOW_BASE_URL", "https://api.chariow.com/v1").rstrip("/")
    headers = _chariow_headers()
    matched_sale = None

    # 1. Interrogation ciblée si sale_id est connu
    if target_sale_id:
        try:
            url = f"{base_url}/sales/{target_sale_id}"
            res = requests.get(url, headers=headers, timeout=_TIMEOUT)
            if res.status_code == 200:
                data = res.json()
                matched_sale = data.get("data") if isinstance(data.get("data"), dict) else data
        except requests.exceptions.RequestException as e:
            logger.warning("[Chariow Sync] Erreur lors de la récupération de la vente %s : %s", target_sale_id, e)

    # 2. Si aucune vente trouvée via target_sale_id, recherche dans les ventes récentes
    if not matched_sale:
        try:
            url = f"{base_url}/sales?per_page=25"
            res = requests.get(url, headers=headers, timeout=_TIMEOUT)
            if res.status_code == 200:
                data = res.json()
                sales_list = data.get("data") if isinstance(data.get("data"), list) else []
                user_email = (getattr(payment.user, "email", "") or "").strip().lower()
                clean_phone = re.sub(r"[^\d]", "", str(payment.phone_number or ""))

                for s in sales_list:
                    # Match par custom_metadata
                    s_metadata = s.get("custom_metadata") or {}
                    s_ref = s_metadata.get("external_reference") or s.get("external_reference")
                    if s_ref and s_ref == payment.external_reference:
                        matched_sale = s
                        break

                    # Match par email ou téléphone pour les ventes 'completed'
                    s_status = s.get("status")
                    cust = s.get("customer") or {}
                    c_email = (cust.get("email") or "").strip().lower()
                    c_phone = ""
                    if isinstance(cust.get("phone"), dict):
                        c_phone = str(cust.get("phone", {}).get("number", ""))
                    elif cust.get("phone"):
                        c_phone = str(cust.get("phone"))
                    c_phone_clean = re.sub(r"[^\d]", "", c_phone)

                    email_match = user_email and c_email and (user_email == c_email)
                    phone_match = clean_phone and c_phone_clean and (
                        clean_phone.endswith(c_phone_clean) or c_phone_clean.endswith(clean_phone)
                    )

                    if s_status in ["completed", "success"] and (email_match or phone_match):
                        matched_sale = s
                        break
        except requests.exceptions.RequestException as e:
            logger.warning("[Chariow Sync] Erreur lors de la recherche des ventes récentes : %s", e)

    if not matched_sale:
        return {
            "success": False,
            "status": payment.status,
            "is_approved": False,
            "message": "Aucune transaction correspondante trouvée sur Chariow."
        }

    sale_status = matched_sale.get("status") or ""
    payment_obj = matched_sale.get("payment") if isinstance(matched_sale.get("payment"), dict) else {}
    payment_status = payment_obj.get("status") if isinstance(payment_obj, dict) else ""
    actual_sale_id = matched_sale.get("id") or target_sale_id

    if actual_sale_id and not payment.chariow_sale_id:
        payment.chariow_sale_id = str(actual_sale_id)
        payment.save(update_fields=["chariow_sale_id"])

    if sale_status in ["completed", "success"] or payment_status in ["success", "completed"]:
        payment.status = Payment.STATUS_APPROVED
        payment.save(update_fields=["status"])
        activate_pass_for_payment(payment)
        logger.info(
            "[Chariow Sync] Paiement %s validé avec succès via l'API Chariow (sale_id=%s)",
            payment.external_reference, actual_sale_id
        )
        return {
            "success": True,
            "status": "approved",
            "is_approved": True,
            "sale_id": actual_sale_id,
            "message": "Pass Semestre activé avec succès."
        }
    elif sale_status in ["failed", "abandoned", "refunded"] or payment_status in ["failed", "abandoned"]:
        payment.status = Payment.STATUS_REJECTED
        payment.save(update_fields=["status"])
        return {
            "success": True,
            "status": "rejected",
            "is_approved": False,
            "sale_id": actual_sale_id,
            "message": "Paiement non validé par Chariow."
        }

    return {
        "success": True,
        "status": payment.status,
        "is_approved": False,
        "sale_id": actual_sale_id,
        "message": f"Vente en attente sur Chariow (statut: {sale_status})."
    }


def handle_chariow_pulse_event(payload, delivery_id=None):
    """
    Traite un événement Pulse reçu de Chariow de façon sécurisée et idempotente.
    
    Événements pris en charge :
    - successful.sale / successful_sale : validation du paiement et activation du Pass
    - failed.sale / failed_sale : échec du paiement
    - abandoned.sale / abandoned_sale : abandon par l'étudiant
    - refunded.sale / refunded_sale : remboursement
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

    # Événements de vente pris en compte (supportant le point et l'underscore)
    SALE_EVENTS = [
        "successful.sale", "successful_sale", "sale.completed", "sale.success", "sale_completed",
        "failed.sale", "failed_sale", "sale.failed",
        "abandoned.sale", "abandoned_sale", "sale.abandoned",
        "refunded.sale", "refunded_sale", "sale.refunded",
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
    if event_name in ["successful.sale", "successful_sale", "sale.completed", "sale.success", "sale_completed"]:
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
