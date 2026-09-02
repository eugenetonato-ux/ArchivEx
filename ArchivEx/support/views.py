import logging
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .models import SupportRequest, SupportReply
from .forms import SupportRequestForm, SupportReplyForm
from contributors.decorators import contributor_required
from notifications.models import Notification

logger = logging.getLogger("django")
User = get_user_model()


# ======================================================
# STUDENT SIDE — Support request creation & history
# ======================================================

def support_create_view(request):
    """
    Permet à un étudiant connecté ou un visiteur anonyme de soumettre une demande de support.
    Une notification d'administration et un email sont automatiquement envoyés.
    """
    is_auth = request.user.is_authenticated
    form = SupportRequestForm(request.POST or None, is_authenticated=is_auth)

    if request.method == "POST" and form.is_valid():
        support_req = form.save(commit=False)
        if is_auth:
            support_req.user = request.user
            student_identity = request.user.get_full_name() or request.user.username
            student_email = request.user.email
        else:
            support_req.user = None
            student_identity = support_req.guest_name or "Visiteur"
            student_email = support_req.guest_email or "Non renseigné"

        support_req.status = "non_lu"
        support_req.save()

        # 1. Notification interne pour les administrateurs
        try:
            admin_users = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
            admin_url = reverse("contributors:admin_support_detail", kwargs={"pk": support_req.pk})
            for admin_u in admin_users:
                Notification.objects.create(
                    recipient=admin_u,
                    notification_type="NEW_SUPPORT",
                    title="Nouveau message support",
                    message=f"Demande support de {student_identity} : « {support_req.get_category_display()} ».",
                    link=admin_url,
                )
        except Exception as err:
            logger.error(f"Erreur lors de la création de la notification support admin : {err}")

        # 2. Email administrateur (fail-safe)
        try:
            target_support_email = getattr(settings, "SUPPORT_EMAIL", None) or getattr(settings, "DEFAULT_FROM_EMAIL", "support@archivex.bj")
            subject = f"[ArchivEx Support] Nouveau message de {student_identity}"
            body_message = f"""Bonjour l'équipe support ArchivEx,

Un nouveau message de support a été soumis.

Expéditeur : {student_identity} ({student_email})
Catégorie / Motif : {support_req.get_category_display()}

Message :
--------------------------------------------------
{support_req.message}
--------------------------------------------------

Pour répondre à cette demande, veuillez vous connecter à l'espace d'administration.
"""
            send_mail(
                subject=subject,
                message=body_message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "support@archivex.bj"),
                recipient_list=[target_support_email],
                fail_silently=True,
            )
        except Exception as err:
            logger.error(f"Erreur lors de l'envoi de l'email de support : {err}")

        messages.success(
            request,
            "✅ Votre demande a bien été envoyée. Notre équipe vous répondra dans les plus brefs délais."
        )
        if is_auth:
            return redirect("support:list")
        return redirect("academics:home")

    context = {
        "form": form,
        "page_title": "Contacter le support",
    }
    return render(request, "support/create.html", context)


@login_required
def support_list_view(request):
    """
    Affiche l'historique des demandes de support de l'étudiant connecté (par compte ou par email).
    """
    user_email = getattr(request.user, "email", "") or ""
    support_requests = SupportRequest.objects.filter(
        Q(user=request.user) | Q(guest_email__iexact=user_email)
    ).prefetch_related("replies").order_by("-created_at")

    context = {
        "support_requests": support_requests,
        "page_title": "Mes demandes de support",
    }
    return render(request, "support/list.html", context)


@login_required
def support_detail_view(request, pk):
    """
    Affiche le détail d'une demande de support de l'étudiant.
    """
    support_request = get_object_or_404(SupportRequest, pk=pk)

    # Sécurité : l'étudiant auteur ou avec le même email peut consulter sa demande
    is_owner = (support_request.user == request.user) or (
        support_request.guest_email and request.user.email and support_request.guest_email.lower() == request.user.email.lower()
    )
    if not is_owner:
        raise PermissionDenied("Vous n'êtes pas autorisé à consulter cette demande.")

    # Marquer les notifications liées comme lues
    Notification.objects.filter(
        recipient=request.user,
        link__contains=f"/support/{pk}/",
        is_read=False,
    ).update(is_read=True)

    context = {
        "support_request": support_request,
        "replies": support_request.replies.select_related("admin_user"),
        "page_title": "Détail de la demande",
    }
    return render(request, "support/detail.html", context)


# ======================================================
# ADMIN SIDE — Support management inside /administration/
# ======================================================

@contributor_required
def admin_support_list_view(request):
    """
    Vue administration : liste de toutes les demandes de support étudiants.
    """
    status_filter = request.GET.get("status", "").strip()
    support_requests = SupportRequest.objects.select_related("user").prefetch_related("replies").order_by("-created_at")

    valid_statuses = [choice[0] for choice in SupportRequest.STATUS_CHOICES]
    if status_filter and status_filter in valid_statuses:
        support_requests = support_requests.filter(status=status_filter)
    else:
        status_filter = ""

    # Stats rapides
    total = SupportRequest.objects.count()
    non_lus = SupportRequest.objects.filter(status="non_lu").count()
    en_cours = SupportRequest.objects.filter(status="en_cours").count()
    repondus = SupportRequest.objects.filter(status="repondu").count()

    context = {
        "support_requests": support_requests,
        "status_filter": status_filter,
        "status_choices": SupportRequest.STATUS_CHOICES,
        "total": total,
        "non_lus": non_lus,
        "en_cours": en_cours,
        "repondus": repondus,
        "page_title": "Support — Demandes étudiants",
    }
    return render(request, "contributors/support/list.html", context)


@contributor_required
def admin_support_detail_view(request, pk):
    """
    Vue administration : détail d'une demande + formulaire de réponse.
    """
    support_request = get_object_or_404(SupportRequest, pk=pk)

    # Marquer les notifications liées comme lues pour cet administrateur
    Notification.objects.filter(
        recipient=request.user,
        link__contains=f"/administration/support/{pk}/",
        is_read=False,
    ).update(is_read=True)

    form = SupportReplyForm()

    if request.method == "POST":
        action = request.POST.get("action", "reply")

        if action == "reply":
            form = SupportReplyForm(request.POST)
            if form.is_valid():
                reply = form.save(commit=False)
                reply.request = support_request
                reply.admin_user = request.user
                reply.save()

                # Mettre à jour le statut
                support_request.status = "repondu"
                support_request.save(update_fields=["status"])

                # Créer une notification pour l'étudiant connecté si présent
                if support_request.user:
                    student_url = reverse("support:detail", kwargs={"pk": support_request.pk})
                    Notification.objects.create(
                        recipient=support_request.user,
                        notification_type="SUPPORT_REPLY",
                        title="Réponse à votre demande de support",
                        message=f"L'équipe ArchivEx a répondu à votre demande : « {support_request.get_category_display()} ».",
                        link=student_url,
                    )
                elif support_request.guest_email:
                    try:
                        send_mail(
                            subject=f"[ArchivEx Support] Réponse à votre demande : {support_request.get_category_display()}",
                            message=f"""Bonjour {support_request.guest_name or 'Visiteur'},

L'équipe ArchivEx a répondu à votre demande de support :

--------------------------------------------------
{reply.message}
--------------------------------------------------

Merci d'utiliser ArchivEx !
""",
                            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "support@archivex.bj"),
                            recipient_list=[support_request.guest_email],
                            fail_silently=True,
                        )
                    except Exception as err:
                        logger.error(f"Erreur d'envoi d'email de réponse invité : {err}")

                messages.success(request, "Réponse enregistrée et envoyée avec succès.")
                return redirect("contributors:admin_support_detail", pk=pk)

        elif action == "set_status":
            new_status = request.POST.get("status")
            valid_statuses = [s[0] for s in SupportRequest.STATUS_CHOICES]
            if new_status in valid_statuses:
                support_request.status = new_status
                support_request.save(update_fields=["status"])
                messages.info(request, f"Statut mis à jour : {support_request.get_status_display()}")
            return redirect("contributors:admin_support_detail", pk=pk)

    context = {
        "support_request": support_request,
        "replies": support_request.replies.select_related("admin_user"),
        "form": form,
        "status_choices": SupportRequest.STATUS_CHOICES,
        "page_title": f"Demande #{pk} — {support_request.get_category_display()}",
    }
    return render(request, "contributors/support/detail.html", context)
