import secrets
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse

logger = logging.getLogger("django")


def generate_temporary_password() -> str:
    """
    Génère un mot de passe temporaire au format ArchivEx-XXXX (ex: ArchivEx-7842)
    facile à taper sur smartphone et sécurisé.
    """
    code = secrets.randbelow(9000) + 1000  # Nombre à 4 chiffres entre 1000 et 9999
    return f"ArchivEx-{code}"


def send_password_reset_email(user, temp_password: str, request=None, admin_user=None) -> tuple[bool, str]:
    """
    Envoie un e-mail officiel au format HTML et texte brut à l'étudiant avec
    ses identifiants, son mot de passe temporaire et les consignes de sécurité.
    
    Retourne (succès: bool, message_info: str).
    """
    if not user or not getattr(user, "email", None):
        return False, "Aucune adresse e-mail associée à ce compte."

    recipient_email = user.email.strip()
    if not recipient_email:
        return False, "Adresse e-mail vide."

    # Déterminer l'URL de connexion
    if request:
        login_url = request.build_absolute_uri(reverse("accounts:login"))
    else:
        site_url = getattr(settings, "SITE_URL", "https://redsandro.pythonanywhere.com").rstrip("/")
        login_url = f"{site_url}{reverse('accounts:login')}"

    user_full_name = user.get_full_name() or user.username
    current_year = timezone.now().year

    context = {
        "user": user,
        "user_full_name": user_full_name,
        "temp_password": temp_password,
        "login_url": login_url,
        "current_year": current_year,
        "admin_user": admin_user,
    }

    subject = "[ArchivEx] Réinitialisation de votre mot de passe"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "support@archivex.bj")

    # Corps texte brut
    text_content = f"""Bonjour {user_full_name},

Votre demande de réinitialisation d'accès a été traitée par l'équipe support ArchivEx.

Voici vos identifiants pour vous connecter :
- Identifiant : {user.username}
- Mot de passe temporaire : {temp_password}

Lien de connexion :
{login_url}

Recommandation de sécurité :
Dès votre connexion, personnalisez votre mot de passe depuis la rubrique "Mon Profil".

L'équipe ArchivEx
"""

    # Corps HTML
    try:
        html_content = render_to_string("emails/password_reset_email.html", context)
    except Exception as e:
        logger.error(f"[Password Reset Email] Erreur lors du rendu du template email: {e}")
        html_content = None

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[recipient_email],
        )
        if html_content:
            msg.attach_alternative(html_content, "text/html")

        sent_count = msg.send(fail_silently=False)
        logger.info(f"[Password Reset Email] E-mail envoyé avec succès à {recipient_email}")
        return True, f"E-mail envoyé avec succès à {recipient_email}."
    except Exception as e:
        logger.error(f"[Password Reset Email] Échec de l'envoi d'e-mail à {recipient_email}: {e}")
        return False, f"Impossible d'envoyer l'e-mail ({e})."
