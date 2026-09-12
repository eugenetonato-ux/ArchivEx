from subscriptions.services import user_has_any_active_pass, get_user_active_accesses


def user_pass_context(request):
    """
    Context processor global rendant disponible le statut du Pass de l'utilisateur dans tous les templates :
    - user_has_active_pass: True si l'utilisateur possède n'importe quel pass actif ou est staff/admin
    - user_active_semester_ids: ensemble des IDs des semestres débloqués pour l'utilisateur
    """
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {
            "user_has_active_pass": False,
            "user_active_semester_ids": set(),
        }

    user = request.user
    if user.is_superuser or user.is_staff or getattr(user, "contributor_profile", None):
        return {
            "user_has_active_pass": True,
            "user_active_semester_ids": set(),
        }

    has_pass = user_has_any_active_pass(user)
    active_accesses = get_user_active_accesses(user)
    active_sem_ids = set(active_accesses.values_list("semester_id", flat=True))

    return {
        "user_has_active_pass": has_pass,
        "user_active_semester_ids": active_sem_ids,
    }
