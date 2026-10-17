import urllib.parse
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods
from django.contrib import messages
from django.conf import settings
from django.urls import reverse

from .models import Ambassador, AmbassadorSale
from academics.models import Semester


@require_http_methods(["GET", "POST"])
def ambassador_dashboard_view(request, token):
    """
    Tableau de bord ultra-simple et épuré pour l'ambassadeur étudiant :
    - Pas de sidebar ni de navbar compliquée
    - Accès direct via son lien privé sans mot de passe
    - Choix/génération de son code personnalisé (doit inclure son prénom)
    - Copie du lien & Bouton direct WhatsApp
    - Compteurs de ventes & gains en FCFA
    - Coordonnées Mobile Money pour recevoir ses gains
    """
    ambassador = get_object_or_404(Ambassador, access_token=token)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "set_code":
            raw_code = request.POST.get("code", "")
            is_valid, result = ambassador.validate_code_candidate(raw_code)
            if is_valid:
                ambassador.code = result
                ambassador.save(update_fields=["code", "updated_at"])
                messages.success(request, f"🎉 Super ! Ton code promo « {result} » est activé et prêt à être partagé !")
            else:
                messages.error(request, result)
            return redirect("ambassadors:dashboard", token=ambassador.access_token)

        elif action == "update_payout":
            operator = request.POST.get("payout_operator", "mtn").strip().lower()
            phone = request.POST.get("payout_phone", "").strip()
            name = request.POST.get("payout_name", "").strip()

            if operator in ["mtn", "moov", "celtiis"]:
                ambassador.payout_operator = operator
            ambassador.payout_phone = phone
            ambassador.payout_name = name
            ambassador.save(update_fields=["payout_operator", "payout_phone", "payout_name", "updated_at"])
            messages.success(request, "Vos coordonnées Mobile Money ont bien été enregistrées.")
            return redirect("ambassadors:dashboard", token=ambassador.access_token)

    # Récupération du premier semestre actif pour construire le lien de partage
    active_semester = Semester.objects.filter(is_active=True, number=1).first() or Semester.objects.filter(is_active=True).first()
    
    if active_semester:
        pass_url_path = reverse("payments:pass_semestre", kwargs={"semester_id": active_semester.id})
    else:
        pass_url_path = "/pass/"

    full_pass_url = request.build_absolute_uri(pass_url_path)
    if ambassador.code:
        share_url = f"{full_pass_url}?ref={ambassador.code}"
    else:
        share_url = full_pass_url

    # Message WhatsApp pré-rempli percutant
    if ambassador.code:
        whatsapp_text = (
            f"Salut ! 👋 Si tu veux débloquer toutes les épreuves et corrigés de notre semestre sur ArchivEx, "
            f"utilise mon lien ou mon code promo *{ambassador.code}* : tu as *200 FCFA de réduction directe* "
            f"(tu paies 4 300 FCFA au lieu de 4 500 FCFA) ! 🚀\n\nClique ici pour en profiter :\n{share_url}"
        )
    else:
        whatsapp_text = f"Accède à tes épreuves et corrigés sur ArchivEx : {full_pass_url}"

    whatsapp_link = f"https://api.whatsapp.com/send?text={urllib.parse.quote(whatsapp_text)}"

    # Liste des ventes récentes
    sales = ambassador.sales.select_related("payment", "payment__user", "payment__semester").order_by("-created_at")

    context = {
        "ambassador": ambassador,
        "share_url": share_url,
        "whatsapp_link": whatsapp_link,
        "sales": sales,
        "active_semester": active_semester,
    }
    return render(request, "ambassadors/dashboard.html", context)


@require_GET
def verify_referral_code_api(request):
    """
    API JSON interrogée en temps réel depuis la page de souscription du Pass Semestre :
    - Vérifie si le code existe et si l'ambassadeur est actif
    - Retourne les montants réduits pour affichage dynamique instantané
    """
    raw_code = request.GET.get("code", "").strip()
    if not raw_code:
        return JsonResponse({
            "valid": False,
            "message": "Veuillez renseigner un code."
        })

    ambassador = Ambassador.objects.filter(code__iexact=raw_code, is_active=True).first()
    if not ambassador:
        return JsonResponse({
            "valid": False,
            "message": "Code promo ou parrainage introuvable ou expiré."
        })

    base_price = getattr(settings, "PASS_SEMESTRE_PRIX_DEFAUT", 4500)
    discount = ambassador.discount_amount or 200
    final_price = max(100, base_price - discount)

    return JsonResponse({
        "valid": True,
        "code": ambassador.code,
        "ambassador_name": ambassador.first_name,
        "discount": discount,
        "base_price": base_price,
        "final_price": final_price,
        "message": f"Code appliqué ! Réduction de {discount} FCFA offerte par {ambassador.first_name}."
    })
