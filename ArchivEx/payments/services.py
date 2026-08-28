import hmac
import hashlib
import json
import re
import uuid
import urllib.request
import urllib.error
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.db import transaction

from .models import Payment, SemesterAccess
from subscriptions.models import UserSubscription


def normalize_benin_phone(phone_input):
    """
    Normalise un numéro de téléphone béninois au format international sans '+' (ex: 22997000000).
    Exemples acceptés : '97000000', '+229 97 00 00 00', '0197000000', '22997000000'.
    """
    if not phone_input:
        raise ValueError("Le numéro de téléphone est obligatoire.")

    cleaned = re.sub(r"[^\d]", "", str(phone_input))

    if cleaned.startswith("00229"):
        cleaned = cleaned[2:]

    if cleaned.startswith("229"):
        digits = cleaned[3:]
    else:
        digits = cleaned

    # Si le numéro commence par 01 (nouveau plan de numérotation Bénin), on le conserve
    if digits.startswith("0") and len(digits) == 10:
        pass
    elif len(digits) == 8:
        pass
    elif len(digits) == 10:
        pass
    else:
        raise ValueError("Format de numéro béninois invalide. Exemple attendu : 97000000 ou 22997000000.")

    return f"229{digits}"


def generate_external_reference():
    """Génère une référence unique d'émanation ArchivEx pour SebPay (ex: ARCHIVEX-PASS-2026-A1B2C3)."""
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
    url = f"{settings.SEBPAY_BASE_URL.rstrip('/')}/collections"
    cb_url = callback_url or getattr(settings, "SEBPAY_CALLBACK_URL", "https://archivex.bj/webhook/sebpay/")

    payload = {
        "amount": int(payment.amount),
        "currency": payment.currency or getattr(settings, "SEBPAY_CURRENCY", "XOF"),
        "phone": payment.phone_number,
        "operator": payment.operator,
        "country": getattr(settings, "SEBPAY_COUNTRY", "BJ"),
        "external_reference": payment.external_reference,
        "callback_url": cb_url,
    }

    headers = {
        "X-Public-Key": getattr(settings, "SEBPAY_PUBLIC_KEY", ""),
        "X-Secret-Key": getattr(settings, "SEBPAY_SECRET_KEY", ""),
        "Content-Type": "application/json",
    }

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode("utf-8")
            res_data = json.loads(res_body)
            # Enregistrer l'ID de transaction SebPay si renvoyé
            sebpay_id = res_data.get("id") or res_data.get("transaction_id") or res_data.get("reference")
            if sebpay_id:
                payment.sebpay_transaction_id = str(sebpay_id)
                payment.save(update_fields=["sebpay_transaction_id"])
            return {"success": True, "data": res_data}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else str(e)
        return {"success": False, "error": f"Erreur SebPay HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"success": False, "error": f"Erreur de connexion SebPay : {str(e)}"}


def verify_sebpay_transaction(reference_or_id):
    """
    Vérifie le statut d'une transaction auprès de SebPay.
    GET https://newapi.sebpay.bj/api/v1/collections/{id_or_reference}
    """
    url = f"{settings.SEBPAY_BASE_URL.rstrip('/')}/collections/{reference_or_id}"
    headers = {
        "X-Public-Key": getattr(settings, "SEBPAY_PUBLIC_KEY", ""),
        "X-Secret-Key": getattr(settings, "SEBPAY_SECRET_KEY", ""),
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode("utf-8")
            return {"success": True, "data": json.loads(res_body)}
    except Exception as e:
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
    - Associe la référence du paiement
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

    # Créer / Activer l'abonnement V2 idempotemment
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
