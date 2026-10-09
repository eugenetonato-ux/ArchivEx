import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.http import JsonResponse

from exams.models import Exam
from .forms import StudentRegistrationForm, StudentLoginForm, StudentProfileForm, ForcePasswordChangeForm, ForgotPasswordForm
from .models import StudentProfile, Favorite, SiteLog, UserDevice, DeviceRevocationLog
from .utils import (
    log_user_action,
    get_or_create_device_id,
    parse_device_info,
    get_client_ip,
    MAX_ALLOWED_DEVICES,
    MAX_DAILY_REVOCATIONS,
    check_revocation_limit_status,
)
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.conf import settings
from payments.models import SemesterAccess

def register_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None):
            return redirect("contributors:admin_dashboard")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # Enregistrer la clé de session pour la protection anti-partage
            user.active_session_key = request.session.session_key
            user.save(update_fields=["active_session_key"])

            # Enregistrement du premier appareil autorisé
            device_id, _ = get_or_create_device_id(request)
            ua_str = request.META.get("HTTP_USER_AGENT", "")
            device_name = parse_device_info(ua_str)
            client_ip = get_client_ip(request)
            UserDevice.objects.get_or_create(
                user=user,
                device_id=device_id,
                defaults={
                    "device_name": device_name,
                    "ip_address": client_ip,
                    "user_agent": ua_str[:500],
                }
            )

            log_user_action(request, "CONNECTION", f"Nouvelle inscription et connexion automatique de l'utilisateur : {user.username} (Appareil: {device_name})")
            messages.success(request, f"Bienvenue {user.first_name} ! Ton compte a été créé avec succès.")
            response = redirect("accounts:dashboard")
            response.set_cookie(
                "ax_device_id",
                device_id,
                max_age=365 * 24 * 3600,
                httponly=True,
                samesite="Lax",
                secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
            )
            return response
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous.")
    else:
        initial_email = request.GET.get("email", "").strip()
        form = StudentRegistrationForm(initial={"email": initial_email} if initial_email else None)

    return render(request, "accounts/register.html", {"form": form})

def login_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, "must_change_password", False):
            return redirect("accounts:force_password_change")
        if request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None):
            return redirect("contributors:admin_dashboard")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = StudentLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()

            # --- CONTRÔLE DE VERROUILLAGE À 2 APPAREILS ---
            is_exempt = user.is_staff or user.is_superuser or getattr(user, "contributor_profile", None)
            device_id, _ = get_or_create_device_id(request)
            ua_str = request.META.get("HTTP_USER_AGENT", "")
            device_name = parse_device_info(ua_str)
            client_ip = get_client_ip(request)

            if not is_exempt:
                existing_device = user.devices.filter(device_id=device_id).first()
                if existing_device:
                    existing_device.device_name = device_name
                    existing_device.ip_address = client_ip
                    existing_device.user_agent = ua_str[:500]
                    existing_device.save()
                else:
                    if user.devices.count() >= MAX_ALLOWED_DEVICES:
                        # Limite atteinte : redirection vers l'écran de sélection de remplacement
                        request.session["pending_device_user_id"] = user.id
                        request.session["pending_device_id"] = device_id
                        request.session["pending_device_name"] = device_name
                        request.session["pending_next_url"] = request.GET.get("next") or ""
                        messages.warning(
                            request,
                            "Votre compte ArchivEx est limité à 2 appareils autorisés. "
                            "Pour connecter cet appareil, sélectionnez celui que vous souhaitez remplacer."
                        )
                        return redirect("accounts:device_limit")
                    else:
                        UserDevice.objects.create(
                            user=user,
                            device_id=device_id,
                            device_name=device_name,
                            ip_address=client_ip,
                            user_agent=ua_str[:500],
                        )

            login(request, user)
            # Enregistrer la clé de session active pour la protection anti-partage de compte
            user.active_session_key = request.session.session_key
            user.save(update_fields=["active_session_key"])
            log_user_action(request, "CONNECTION", f"Connexion réussie de l'utilisateur : {user.username} (Appareil: {device_name})")
            
            # Vérification de sécurité : l'étudiant doit changer son mot de passe temporaire
            if getattr(user, "must_change_password", False):
                messages.warning(
                    request,
                    "Pour votre sécurité, veuillez définir votre nouveau mot de passe personnel avant de continuer."
                )
                response = redirect("accounts:force_password_change")
            else:
                messages.success(request, f"Ravi de te revoir, {user.first_name or user.username} !")
                next_url = request.GET.get("next")
                from django.urls import reverse
                if not next_url or next_url == "/" or next_url == reverse("academics:home"):
                    if user.is_staff or user.is_superuser or getattr(user, "contributor_profile", None):
                        response = redirect("contributors:admin_dashboard")
                    else:
                        response = redirect("accounts:dashboard")
                else:
                    response = redirect(next_url)

            # Poser le cookie d'appareil persistant (1 an)
            response.set_cookie(
                "ax_device_id",
                device_id,
                max_age=365 * 24 * 3600,
                httponly=True,
                samesite="Lax",
                secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
            )
            return response
        else:
            if getattr(form, "account_not_found", False):
                messages.error(
                    request,
                    "Identifiant non reconnu dans la base de données. Vous n'avez pas de compte ? Nous vous invitons à vous inscrire."
                )
            elif getattr(form, "password_incorrect", False):
                messages.error(
                    request,
                    "Identifiant reconnu, mais le mot de passe saisi est incorrect. Veuillez vérifier votre mot de passe."
                )
            else:
                messages.error(request, "Email ou mot de passe incorrect.")
    else:
        form = StudentLoginForm()

    initial_identifier = request.POST.get("username") or request.GET.get("email") or ""
    return render(request, "accounts/login.html", {
        "form": form,
        "initial_identifier": initial_identifier,
    })


def device_limit_view(request):
    """
    Vue affichée lorsqu'un étudiant tente de se connecter sur un 3e appareil.
    Présente ses 2 appareils actuels et lui permet d'en révoquer un pour autoriser le nouveau.
    Règle anti-partage stricte : Maximum 2 révocations par 24h. Au-delà, blocage 24h.
    """
    user_id = request.session.get("pending_device_user_id")
    device_id = request.session.get("pending_device_id")
    new_device_name = request.session.get("pending_device_name", "Nouvel appareil")
    next_url = request.session.get("pending_next_url")

    if not user_id or not device_id:
        return redirect("accounts:login")

    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    current_devices = user.devices.all()

    can_revoke, remaining_revocations, cooldown_until = check_revocation_limit_status(user)

    if request.method == "POST":
        if not can_revoke:
            cooldown_str = cooldown_until.strftime("%d/%m/%Y à %H:%M") if cooldown_until else "24 heures"
            messages.error(
                request,
                f"Remplacement refusé : Votre compte a atteint la limite de 2 révocations par 24h. "
                f"Par mesure de sécurité anti-partage de compte, les remplacements sont bloqués jusqu'au {cooldown_str}."
            )
            return redirect("accounts:device_limit")

        replace_device_id = request.POST.get("replace_device_id")
        if replace_device_id:
            old_device = user.devices.filter(device_id=replace_device_id).first()
            old_device_name = old_device.device_name if old_device else "Ancien appareil"
            user.devices.filter(device_id=replace_device_id).delete()

            # Enregistrer la révocation dans le journal anti-partage
            client_ip = get_client_ip(request)
            DeviceRevocationLog.objects.create(
                user=user,
                revoked_device_name=old_device_name,
                ip_address=client_ip,
            )

            # Enregistrer le nouvel appareil
            ua_str = request.META.get("HTTP_USER_AGENT", "")
            UserDevice.objects.create(
                user=user,
                device_id=device_id,
                device_name=new_device_name,
                ip_address=client_ip,
                user_agent=ua_str[:500],
            )

            # Connecter l'utilisateur
            login(request, user)
            user.active_session_key = request.session.session_key
            user.save(update_fields=["active_session_key"])

            # Nettoyer la session temporaire
            request.session.pop("pending_device_user_id", None)
            request.session.pop("pending_device_id", None)
            request.session.pop("pending_device_name", None)
            request.session.pop("pending_next_url", None)

            log_user_action(request, "CONNECTION", f"Remplacement d'appareil effectué : {new_device_name} autorisé, {old_device_name} révoqué.")
            messages.success(request, f"Votre appareil « {new_device_name} » a été activé avec succès !")

            from django.urls import reverse
            redirect_target = next_url if next_url and next_url != "/" else reverse("accounts:dashboard")
            response = redirect(redirect_target)
            response.set_cookie(
                "ax_device_id",
                device_id,
                max_age=365 * 24 * 3600,
                httponly=True,
                samesite="Lax",
                secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
            )
            return response

    return render(request, "accounts/device_limit.html", {
        "user_target": user,
        "new_device_name": new_device_name,
        "current_devices": current_devices,
        "can_revoke": can_revoke,
        "remaining_revocations": remaining_revocations,
        "cooldown_until": cooldown_until,
        "max_daily_revocations": MAX_DAILY_REVOCATIONS,
    })


@login_required
def revoke_device_view(request, device_pk):
    """Permet à un étudiant de révoquer l'un de ses appareils enregistrés depuis son profil."""
    if request.method == "POST":
        can_revoke, remaining_revocations, cooldown_until = check_revocation_limit_status(request.user)
        if not can_revoke:
            cooldown_str = cooldown_until.strftime("%d/%m/%Y à %H:%M") if cooldown_until else "24 heures"
            messages.error(
                request,
                f"Action refusée : Vous avez atteint la limite de 2 révocations par 24h. "
                f"Tout nouveau changement d'appareil est suspendu jusqu'au {cooldown_str}."
            )
            return redirect("accounts:profile")

        device = get_object_or_404(UserDevice, pk=device_pk, user=request.user)
        device_name = device.device_name
        current_device_id = request.COOKIES.get("ax_device_id")
        is_current = (device.device_id == current_device_id)

        device.delete()

        # Enregistrer la révocation dans le journal anti-partage
        DeviceRevocationLog.objects.create(
            user=request.user,
            revoked_device_name=device_name,
            ip_address=get_client_ip(request),
        )

        log_user_action(request, "MODIFICATION", f"Révocation d'appareil : {device_name}")

        if is_current:
            logout(request)
            messages.info(request, "Cet appareil a été révoqué. Votre session a été fermée.")
            return redirect("accounts:login")

        messages.success(request, f"L'appareil « {device_name} » a été retiré de votre compte. Un nouvel emplacement est libre.")
    return redirect("accounts:profile")


@login_required
def force_password_change_view(request):
    """
    Vue obligatoire lorsqu'un utilisateur s'est connecté avec un mot de passe temporaire
    ou a le flag must_change_password activé.
    """
    if not getattr(request.user, "must_change_password", False):
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = ForcePasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            request.user.must_change_password = False
            request.user.save(update_fields=["must_change_password"])

            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)

            # Après update_session_auth_hash, la clé de session est régénérée
            request.user.active_session_key = request.session.session_key
            request.user.save(update_fields=["active_session_key"])

            log_user_action(
                request,
                "MODIFICATION",
                "Mise à jour sécurisée du mot de passe temporaire suite à demande support"
            )
            messages.success(
                request,
                "Votre mot de passe personnel a été enregistré avec succès ! Le mot de passe temporaire n'est plus actif."
            )
            if request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None):
                return redirect("contributors:admin_dashboard")
            return redirect("accounts:dashboard")
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous pour sécuriser votre mot de passe.")
    else:
        form = ForcePasswordChangeForm(user=request.user)

    return render(request, "accounts/force_password_change.html", {"form": form})


def mask_email(email: str) -> str:
    """Masque une adresse email pour protéger la confidentialité (ex: jean.dupont@gmail.com -> je***t@gmail.com)."""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = f"{local[:2]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def forgot_password_view(request):
    """
    Permet à l'étudiant d'obtenir IMMÉDIATEMENT un mot de passe temporaire par email
    sans dépendre d'une action manuelle de l'administrateur.
    """
    if request.user.is_authenticated:
        if getattr(request.user, "must_change_password", False):
            return redirect("accounts:force_password_change")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            identifier = form.cleaned_data["identifier"]
            User = get_user_model()
            user = User.objects.filter(
                Q(email__iexact=identifier) | Q(username__iexact=identifier)
            ).first()

            if user and user.email:
                from .services import process_automated_password_reset
                email_sent, email_info, temp_pwd = process_automated_password_reset(
                    user=user,
                    request=request,
                )

                log_user_action(
                    request,
                    "MODIFICATION",
                    f"Réinitialisation automatique du mot de passe pour {user.username}"
                )

                # Traçabilité dans SupportRequest
                try:
                    from support.models import SupportRequest, SupportReply
                    sr = SupportRequest.objects.create(
                        user=user,
                        guest_name=user.get_full_name() or user.username,
                        guest_email=user.email,
                        category="recuperation_mot_de_passe",
                        message="Demande de mot de passe oublié déclenchée en libre-service par l'utilisateur.",
                        status="repondu",
                    )
                    SupportReply.objects.create(
                        request=sr,
                        admin_user=None,
                        message=f"Mot de passe temporaire ({temp_pwd}) généré et envoyé automatiquement par e-mail à {user.email}.",
                    )
                except Exception as e:
                    import logging
                    logging.getLogger("django").error(f"[forgot_password_view] Erreur trace support: {e}")

                masked = mask_email(user.email)
                if email_sent:
                    messages.success(
                        request,
                        f"Un mot de passe temporaire a été généré et envoyé à l'adresse {masked}. "
                        "Consultez votre messagerie (y compris vos courriers indésirables / spams Gmail), "
                        "puis connectez-vous. Le système vous invitera obligatoirement à choisir votre mot de passe personnel dès votre connexion."
                    )
                else:
                    messages.warning(
                        request,
                        f"Le mot de passe temporaire a été activé sur votre compte, mais le service d'envoi d'e-mail a rencontré une difficulté ({email_info}). "
                        "Veuillez vérifier votre messagerie ou contacter le support si vous ne recevez rien."
                    )

                return redirect(f"{reverse('accounts:login')}?email={user.username or user.email}")
            else:
                messages.error(
                    request,
                    "Aucun compte associé à cette adresse e-mail ou cet identifiant n'a été trouvé. "
                    "Veuillez vérifier l'adresse saisie ou créer un nouveau compte si vous n'êtes pas encore inscrit."
                )
    else:
        initial_email = request.GET.get("email", "").strip()
        form = ForgotPasswordForm(initial={"identifier": initial_email} if initial_email else None)

    return render(request, "accounts/forgot_password.html", {"form": form})



def logout_view(request):
    username = request.user.username if request.user.is_authenticated else "Anonyme"
    log_user_action(request, "CONNECTION", f"Déconnexion de l'utilisateur : {username}")
    # Effacer la clé de session active proprement lors de la déconnexion
    if request.user.is_authenticated:
        try:
            request.user.active_session_key = None
            request.user.save(update_fields=["active_session_key"])
        except Exception:
            pass
    logout(request)
    messages.info(request, "Tu es à présent déconnecté.")
    return redirect("academics:home")

@login_required
def dashboard_view(request):
    from academics.context import get_current_school
    current_school = get_current_school(request)

    profile = getattr(request.user, "profile", None)
    if not profile:
        # Pour les administrateurs / staff qui consultent l'espace étudiant,
        # associer leur profil d'aperçu à leur école active courante (ex: FASEG)
        from academics.models import Filiere, School, Level
        default_school = current_school or School.objects.first()
        if default_school:
            default_filiere = Filiere.objects.filter(school=default_school).first()
            default_level = (default_filiere.level if default_filiere else None) or Level.objects.filter(school=default_school).first() or Level.objects.first()
            if default_filiere and default_level:
                profile, _ = StudentProfile.objects.get_or_create(
                    user=request.user,
                    defaults={
                        "school": default_school,
                        "filiere": default_filiere,
                        "level": default_level,
                    }
                )
    elif profile and (request.user.is_staff or request.user.is_superuser or getattr(request.user, "contributor_profile", None)):
        # Si un admin a changé de filière ou d'école active dans l'administration, synchroniser son aperçu
        admin_filiere_id = request.session.get("admin_active_filiere_id")
        if admin_filiere_id and admin_filiere_id != "all":
            admin_fil = Filiere.objects.filter(id=admin_filiere_id).first()
            if admin_fil and profile.filiere_id != admin_fil.id:
                profile.filiere = admin_fil
                profile.school = admin_fil.school
                profile.level = admin_fil.level or profile.level
                profile.save()
        elif current_school and profile.school_id != current_school.id:
            profile.school = current_school
            filiere_cand = Filiere.objects.filter(school=current_school).first()
            if filiere_cand:
                profile.filiere = filiere_cand
                profile.level = filiere_cand.level or profile.level
            profile.save()

    # Initialiser toutes les variables
    active_semester = None
    user_ues = []
    semester_subjects_count = 0
    semester_exams_count = 0
    semester_summaries_count = 0
    semester_guides_count = 0
    recent_exams = []
    recent_summaries = []
    recent_guides = []
    recent_articles = []

    user_school = profile.school if profile else current_school

    # Auto-healing : activation immédiate des paiements validés en attente de liaison
    from payments.models import Payment, SemesterAccess
    from payments.services import activate_pass_for_payment
    unlinked_payments = Payment.objects.filter(
        user=request.user,
        status__in=["APPROVED", "reussi", "approved", "success"],
        semester_access__isnull=True,
    )
    for unp in unlinked_payments:
        try:
            activate_pass_for_payment(unp)
        except Exception:
            pass

    # Active accesses (Legacy & V2)
    active_accesses = SemesterAccess.objects.filter(
        Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status__in=["APPROVED", "reussi", "approved", "success"]))
    )
    if user_school:
        active_accesses = active_accesses.filter(filiere__school=user_school)
    active_accesses = active_accesses.select_related("semester", "filiere", "level", "school").distinct()

    from subscriptions.models import UserSubscription
    from subscriptions.services import can_user_access
    from content.models import Summary, Guide, Article
    from academics.models import Semester, Subject, Filiere

    user_subscriptions = UserSubscription.objects.filter(
        user=request.user, is_active=True
    )
    if user_school:
        user_subscriptions = user_subscriptions.filter(school=user_school)
    user_subscriptions = user_subscriptions.select_related("school", "filiere", "semester")

    # Favorites (scopés sur l'école de l'étudiant si définie)
    favorites = Favorite.objects.filter(user=request.user)
    if user_school:
        favorites = favorites.filter(exam__filiere__school=user_school)
    favorites = favorites.select_related(
        "exam", "exam__subject", "exam__filiere"
    ).order_by("-created_at")[:6]

    # Filière active de l'étudiant
    filiere = None
    if profile and profile.filiere and (not user_school or profile.filiere.school_id == user_school.id):
        filiere = profile.filiere
    else:
        active_access = active_accesses.first()
        if active_access and active_access.filiere and (not user_school or active_access.filiere.school_id == user_school.id):
            filiere = active_access.filiere
        elif user_school:
            filiere = Filiere.objects.filter(school=user_school).first()
        else:
            filiere = None

    available_semesters = Semester.objects.filter(filiere=filiere) if filiere else Semester.objects.none()
    selected_semester_id = request.GET.get("semester")
    if selected_semester_id and available_semesters.exists():
        active_semester = available_semesters.filter(id=selected_semester_id).first()
    if not active_semester and available_semesters.exists():
        active_access = active_accesses.first()
        if active_access and active_access.semester and active_access.semester in available_semesters:
            active_semester = active_access.semester
        else:
            active_semester = available_semesters.first()

    # Calcul des métriques réelles depuis la base de données
    if active_semester:
        semester_subjects_count = Subject.objects.filter(semester=active_semester, is_active=True).count()
        semester_exams_count = Exam.objects.filter(semester=active_semester, is_published=True).count()
        semester_summaries_count = Summary.objects.filter(subject__semester=active_semester, publication_status="PUBLISHED").count()
        semester_guides_count = Guide.objects.filter(subject__semester=active_semester, publication_status="PUBLISHED").count()

        user_ues = Subject.objects.filter(semester=active_semester, is_active=True).annotate(
            exams_num=Count("exams", filter=Q(exams__is_published=True))
        )
        recent_exams = Exam.objects.filter(
            semester=active_semester, is_published=True
        ).select_related("subject", "semester", "filiere")[:6]
    elif filiere:
        semester_subjects_count = Subject.objects.filter(semester__filiere=filiere, is_active=True).count()
        semester_exams_count = Exam.objects.filter(filiere=filiere, is_published=True).count()
        semester_summaries_count = Summary.objects.filter(subject__semester__filiere=filiere, publication_status="PUBLISHED").count()
        semester_guides_count = Guide.objects.filter(subject__semester__filiere=filiere, publication_status="PUBLISHED").count()

        user_ues = Subject.objects.filter(semester__filiere=filiere, is_active=True).annotate(
            exams_num=Count("exams", filter=Q(exams__is_published=True))
        )
        recent_exams = Exam.objects.filter(
            filiere=filiere, is_published=True
        ).select_related("subject", "semester", "filiere")[:6]
    else:
        # Aucun mélange inter-écoles : tous les compteurs restent à zéro si l'école n'a pas encore de filière ou de document !
        semester_subjects_count = 0
        semester_exams_count = 0
        semester_summaries_count = 0
        semester_guides_count = 0
        user_ues = []
        recent_exams = []

    for exam in recent_exams:
        exam.user_has_access = can_user_access(request.user, exam)

    # Summaries, Guides, Articles - scopés sur la filière et le semestre
    recent_summaries_qs = Summary.objects.filter(publication_status="PUBLISHED")
    recent_guides_qs = Guide.objects.filter(publication_status="PUBLISHED")
    if active_semester:
        recent_summaries_qs = recent_summaries_qs.filter(subject__semester=active_semester)
        recent_guides_qs = recent_guides_qs.filter(subject__semester=active_semester)
    elif filiere:
        recent_summaries_qs = recent_summaries_qs.filter(subject__semester__filiere=filiere)
        recent_guides_qs = recent_guides_qs.filter(subject__semester__filiere=filiere)
    elif user_school:
        recent_summaries_qs = recent_summaries_qs.filter(subject__semester__filiere__school=user_school)
        recent_guides_qs = recent_guides_qs.filter(subject__semester__filiere__school=user_school)

    recent_summaries = recent_summaries_qs.select_related("subject")[:4]
    for s in recent_summaries:
        s.user_has_access = can_user_access(request.user, s)

    recent_guides = recent_guides_qs.select_related("subject")[:4]
    for g in recent_guides:
        g.user_has_access = can_user_access(request.user, g)

    recent_articles = Article.objects.filter(publication_status="PUBLISHED")[:3]

    active_pass = active_accesses.exists() or user_subscriptions.filter(is_active=True).exists()

    # DIAGRAMME CIRCULAIRE : Activité et consultations des UE par l'étudiant
    from academics.models import SubjectConsultation

    UE_PALETTE = [
        "#2563EB",  # Bleu Royal ArchivEx
        "#10B981",  # Vert Émeraude
        "#8B5CF6",  # Violet Améthyste
        "#F59E0B",  # Ambre Doré
        "#EC4899",  # Rose Framboise
        "#06B6D4",  # Cyan Océan
        "#F97316",  # Orange Corail
        "#6366F1",  # Indigo Nuit
        "#14B8A6",  # Teal Lagon
        "#84CC16",  # Citron Vert
        "#D946EF",  # Fuchsia
        "#64748B",  # Ardoise Élégante
    ]

    try:
        consultation_counts = dict(
            SubjectConsultation.objects.filter(
                user=request.user,
                subject__in=user_ues
            ).values("subject_id").annotate(total=Count("id")).values_list("subject_id", "total")
        )
    except Exception:
        consultation_counts = {}

    ue_chart_labels = []
    ue_chart_counts = []
    ue_chart_colors = []
    ue_legend_items = []

    total_ue_consultations = sum(consultation_counts.values())

    for idx, ue in enumerate(user_ues):
        cnt = consultation_counts.get(ue.id, 0)
        color = UE_PALETTE[idx % len(UE_PALETTE)]
        percent = round((cnt / total_ue_consultations * 100), 1) if total_ue_consultations > 0 else 0

        ue_chart_labels.append(ue.name)
        ue_chart_counts.append(cnt)
        ue_chart_colors.append(color)

        ue_legend_items.append({
            "id": ue.id,
            "name": ue.name,
            "code": getattr(ue, "code", "") or f"UE-{idx+1}",
            "count": cnt,
            "percent": percent,
            "color": color,
            "exams_num": getattr(ue, "exams_num", 0),
        })

    # Classement pour identifier l'UE la plus consultée et celle à approfondir
    sorted_by_activity = sorted(ue_legend_items, key=lambda x: x["count"], reverse=True)
    most_consulted_ue = sorted_by_activity[0] if sorted_by_activity and sorted_by_activity[0]["count"] > 0 else None
    least_consulted_ue = sorted_by_activity[-1] if sorted_by_activity else None

    ue_chart_json = json.dumps({
        "labels": ue_chart_labels,
        "counts": ue_chart_counts,
        "colors": ue_chart_colors,
        "total": total_ue_consultations,
        "has_activity": total_ue_consultations > 0,
    }, ensure_ascii=False)

    context = {
        "profile": profile,
        "filiere": filiere,
        "available_semesters": available_semesters,
        "active_accesses": active_accesses,
        "user_subscriptions": user_subscriptions,
        "active_pass": active_pass,
        "has_semester_access": active_pass,
        "active_semester": active_semester,
        "semester_subjects_count": semester_subjects_count,
        "semester_exams_count": semester_exams_count,
        "semester_summaries_count": semester_summaries_count,
        "semester_guides_count": semester_guides_count,
        "user_ues": user_ues,
        "favorites": favorites,
        "recent_exams": recent_exams,
        "recent_summaries": recent_summaries,
        "recent_guides": recent_guides,
        "recent_articles": recent_articles,
        "ue_chart_json": ue_chart_json,
        "ue_legend_items": ue_legend_items,
        "most_consulted_ue": most_consulted_ue,
        "least_consulted_ue": least_consulted_ue,
        "total_ue_consultations": total_ue_consultations,
    }
    return render(request, "dashboard/dashboard.html", context)

@login_required
def favorites_list_view(request):
    user_accesses = set(
        SemesterAccess.objects.filter(
            Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status__in=["APPROVED", "reussi", "approved", "success"]))
        ).values_list("semester_id", flat=True)
    )
    favorites = Favorite.objects.filter(user=request.user).select_related(
        "exam", "exam__subject", "exam__semester", "exam__filiere", "exam__level", "exam__academic_year"
    ).order_by("-created_at")

    for fav in favorites:
        fav.exam.user_has_access = fav.exam.is_free or (fav.exam.semester_id in user_accesses)

    return render(request, "dashboard/favoris.html", {"favorites": favorites})

@login_required
def profile_view(request):
    profile = getattr(request.user, "profile", None)

    if request.method == "POST":
        user = request.user
        if "first_name" in request.POST:
            user.first_name = request.POST.get("first_name", "").strip()
        if "last_name" in request.POST:
            user.last_name = request.POST.get("last_name", "").strip()
        user.save()

        if profile:
            form = StudentProfileForm(request.POST, request.FILES, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Ton profil a été mis à jour avec succès !")
                return redirect("accounts:profile")
            else:
                messages.error(request, "Veuillez vérifier les informations saisies.")
        else:
            form = StudentProfileForm(request.POST, request.FILES)
            if form.is_valid():
                prof = form.save(commit=False)
                prof.user = user
                prof.save()
                messages.success(request, "Profil créé avec succès !")
                return redirect("accounts:profile")
            else:
                messages.error(request, "Veuillez vérifier les informations saisies.")
    else:
        form = StudentProfileForm(instance=profile) if profile else StudentProfileForm(initial={
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
        })

    # Auto-healing : activation immédiate des paiements validés en attente de liaison
    from payments.models import Payment, SemesterAccess
    from payments.services import activate_pass_for_payment
    unlinked_payments = Payment.objects.filter(
        user=request.user,
        status__in=["APPROVED", "reussi", "approved", "success"],
        semester_access__isnull=True,
    )
    for unp in unlinked_payments:
        try:
            activate_pass_for_payment(unp)
        except Exception:
            pass

    active_accesses = SemesterAccess.objects.filter(
        Q(user=request.user) & (Q(activated_at__isnull=False) | Q(payments__status__in=["APPROVED", "reussi", "approved", "success"]))
    ).select_related("semester", "filiere", "level", "school").distinct()

    devices = request.user.devices.all()
    current_device_id = request.COOKIES.get("ax_device_id", "")
    can_revoke, remaining_revocations, cooldown_until = check_revocation_limit_status(request.user)

    context = {
        "profile": profile,
        "form": form,
        "active_accesses": active_accesses,
        "devices": devices,
        "max_devices": MAX_ALLOWED_DEVICES,
        "current_device_id": current_device_id,
        "can_revoke": can_revoke,
        "remaining_revocations": remaining_revocations,
        "cooldown_until": cooldown_until,
        "max_daily_revocations": MAX_DAILY_REVOCATIONS,
    }
    return render(request, "dashboard/profil.html", context)

from academics.models import Level, Filiere

def api_levels_view(request):
    """API JSON retournant les niveaux d'études filtrés par école."""
    school_id = request.GET.get("school_id")
    levels = Level.objects.filter(is_active=True)
    if school_id:
        levels = levels.filter(Q(school_id=school_id) | Q(school__isnull=True))
    data = [{"id": l.id, "name": l.name, "code": l.code} for l in levels]
    return JsonResponse({"levels": data})

def api_filieres_view(request):
    """API JSON retournant les filières filtrées par école et niveau."""
    school_id = request.GET.get("school_id")
    level_id = request.GET.get("level_id")
    filieres = Filiere.objects.filter(is_active=True)
    if school_id:
        filieres = filieres.filter(school_id=school_id)
    if level_id:
        filieres = filieres.filter(level_id=level_id)
    data = [{"id": f.id, "name": f.name} for f in filieres]
    return JsonResponse({"filieres": data})

import json
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def api_log_click_view(request):
    """API JSON pour enregistrer un événement de clic depuis l'interface publique."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            button_label = str(data.get("label", "Bouton inconnu"))[:100]
            element_id = str(data.get("element_id", ""))[:100]
            page_title = str(data.get("page_title", ""))[:150]
            
            desc = f"Clic public : '{button_label}'"
            if element_id:
                desc += f" (ID: {element_id})"
            if page_title:
                desc += f" sur la page [{page_title}]"
                
            log_user_action(request, "CLICK", desc)
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
