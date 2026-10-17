from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.urls import reverse
from django.db.models import Sum, Q

from .models import Ambassador, AmbassadorSale


def is_admin_or_contributor(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff or getattr(user, "contributor_profile", None))


@login_required
def ambassador_admin_list_view(request):
    """
    Gestion des Ambassadeurs dans le panneau d'administration ArchivEx :
    - Liste de tous les ambassadeurs avec statistiques en direct
    - Ajout rapide d'un nouvel ambassadeur (Prénom, Nom, Téléphone WhatsApp)
    - Copie du lien d'accès privé à envoyer par WhatsApp
    - Marquer les commissions comme reversées (Mobile Money envoyé)
    """
    if not is_admin_or_contributor(request.user):
        messages.error(request, "Accès réservé à l'équipe d'administration.")
        return redirect("contributors:admin_login")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_ambassador":
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            phone = request.POST.get("phone_number", "").strip()
            notes = request.POST.get("notes", "").strip()

            if not first_name:
                messages.error(request, "Le prénom est obligatoire pour créer un ambassadeur.")
            else:
                amb = Ambassador.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=phone,
                    notes=notes,
                    is_active=True,
                )
                dash_url = request.build_absolute_uri(reverse("ambassadors:dashboard", kwargs={"token": amb.access_token}))
                messages.success(
                    request,
                    f"Ambassadeur {amb.full_name} créé avec succès ! Lien privé : {dash_url}"
                )
            return redirect("ambassadors:admin_list")

        elif action == "toggle_active":
            amb_id = request.POST.get("ambassador_id")
            amb = get_object_or_404(Ambassador, pk=amb_id)
            amb.is_active = not amb.is_active
            amb.save(update_fields=["is_active"])
            status_str = "activé" if amb.is_active else "désactivé"
            messages.info(request, f"L'ambassadeur {amb.full_name} a été {status_str}.")
            return redirect("ambassadors:admin_list")

        elif action == "mark_payout":
            amb_id = request.POST.get("ambassador_id")
            amb = get_object_or_404(Ambassador, pk=amb_id)
            ref_tx = request.POST.get("payout_reference", "").strip()
            now = timezone.now()

            pending_sales = amb.sales.filter(status="APPROVED")
            count = pending_sales.count()
            if count > 0:
                pending_sales.update(status="PAID_OUT", paid_out_at=now, payout_reference=ref_tx)
                messages.success(request, f"{count} commission(s) marquée(s) comme reversée(s) pour {amb.full_name}.")
            else:
                messages.warning(request, f"Aucune commission en attente pour {amb.full_name}.")
            return redirect("ambassadors:admin_list")

    # Données et statistiques globales
    ambassadors = Ambassador.objects.prefetch_related("sales").order_by("-created_at")

    total_ambassadors = ambassadors.count()
    active_ambassadors = ambassadors.filter(is_active=True).count()
    
    all_sales = AmbassadorSale.objects.filter(status__in=["APPROVED", "PAID_OUT"])
    total_sales_count = all_sales.count()
    total_commissions_paid = AmbassadorSale.objects.filter(status="PAID_OUT").aggregate(s=Sum("commission_amount"))["s"] or 0
    total_commissions_pending = AmbassadorSale.objects.filter(status="APPROVED").aggregate(s=Sum("commission_amount"))["s"] or 0

    # Attacher l'URL absolue à chaque ambassadeur pour copie facile
    for amb in ambassadors:
        amb.full_dashboard_url = request.build_absolute_uri(
            reverse("ambassadors:dashboard", kwargs={"token": amb.access_token})
        )

    context = {
        "ambassadors": ambassadors,
        "total_ambassadors": total_ambassadors,
        "active_ambassadors": active_ambassadors,
        "total_sales_count": total_sales_count,
        "total_commissions_paid": total_commissions_paid,
        "total_commissions_pending": total_commissions_pending,
    }
    return render(request, "contributors/ambassadors/list.html", context)
