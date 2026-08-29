from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .models import SupportRequest, SupportReply
from .forms import SupportRequestForm, SupportReplyForm
from contributors.decorators import contributor_required
from notifications.models import Notification


# ======================================================
# STUDENT SIDE — Support request creation & history
# ======================================================

@login_required
def support_create_view(request):
    """
    Permet à un étudiant authentifié de soumettre une demande de support.
    Son identité est automatiquement associée à la demande.
    """
    form = SupportRequestForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        support_req = form.save(commit=False)
        support_req.user = request.user
        support_req.status = "non_lu"
        support_req.save()
        messages.success(
            request,
            "✅ Votre demande a bien été envoyée. Notre équipe vous répondra dans les plus brefs délais."
        )
        return redirect("support:list")

    context = {
        "form": form,
        "page_title": "Contacter le support",
    }
    return render(request, "support/create.html", context)


@login_required
def support_list_view(request):
    """
    Affiche l'historique des demandes de support de l'étudiant connecté.
    Seules ses propres demandes sont visibles.
    """
    support_requests = SupportRequest.objects.filter(
        user=request.user
    ).prefetch_related("replies")

    context = {
        "support_requests": support_requests,
        "page_title": "Mes demandes de support",
    }
    return render(request, "support/list.html", context)


@login_required
def support_detail_view(request, pk):
    """
    Affiche le détail d'une demande de support de l'étudiant.
    Seul l'auteur de la demande peut y accéder.
    """
    support_request = get_object_or_404(SupportRequest, pk=pk)

    # Sécurité : seul l'auteur peut voir sa demande
    if support_request.user != request.user:
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
    status_filter = request.GET.get("status", "")
    support_requests = SupportRequest.objects.select_related("user").prefetch_related("replies")

    if status_filter:
        support_requests = support_requests.filter(status=status_filter)

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
    La réponse est visible uniquement par l'étudiant concerné.
    Après réponse : status → 'repondu', notification créée pour l'étudiant.
    """
    support_request = get_object_or_404(SupportRequest, pk=pk)
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

                # Créer une notification pour l'étudiant concerné uniquement
                student_url = reverse("support:detail", kwargs={"pk": support_request.pk})
                Notification.objects.create(
                    recipient=support_request.user,
                    notification_type="SUPPORT_REPLY",
                    title="Réponse à votre demande de support",
                    message=f"L'équipe ArchivEx a répondu à votre demande : « {support_request.get_category_display()} ».",
                    link=student_url,
                )

                messages.success(request, "✅ Réponse envoyée à l'étudiant avec succès.")
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
