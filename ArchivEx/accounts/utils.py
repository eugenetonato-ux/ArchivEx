import logging
from .models import SiteLog

def get_client_ip(request):
    if not request:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def log_user_action(request, action_type, description):
    try:
        user = request.user if (request and hasattr(request, 'user') and request.user.is_authenticated) else None
        path = (request.path[:250]) if (request and hasattr(request, 'path') and request.path) else None
        ip_address = get_client_ip(request)
        if ip_address:
            ip_address = ip_address[:45]
        user_agent = (request.META.get('HTTP_USER_AGENT', '')[:500]) if request else ''
        
        SiteLog.objects.create(
            user=user,
            action_type=action_type,
            description=str(description)[:1000] if description else "",
            path=path,
            ip_address=ip_address,
            user_agent=user_agent
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error creating SiteLog: {e}")


MAX_ALLOWED_DEVICES = 2
MAX_DAILY_REVOCATIONS = 2
REVOCATION_COOLDOWN_HOURS = 24


def get_user_recent_revocations(user):
    """Retourne le QuerySet des révocations effectuées par l'utilisateur au cours des dernières 24h."""
    from datetime import timedelta
    from django.utils import timezone
    since = timezone.now() - timedelta(hours=REVOCATION_COOLDOWN_HOURS)
    return user.device_revocations.filter(created_at__gte=since)


def check_revocation_limit_status(user):
    """
    Vérifie si l'utilisateur a le droit de révoquer ou de remplacer un appareil.
    Retourne : (can_revoke: bool, remaining_revocations: int, cooldown_until: datetime or None)
    """
    from datetime import timedelta
    from django.utils import timezone

    recent = get_user_recent_revocations(user)
    count = recent.count()
    remaining = max(0, MAX_DAILY_REVOCATIONS - count)

    if count >= MAX_DAILY_REVOCATIONS:
        # Déblocage après 24h glissantes à compter de la première révocation
        oldest_in_window = recent.order_by("created_at").first()
        cooldown_until = oldest_in_window.created_at + timedelta(hours=REVOCATION_COOLDOWN_HOURS)
        return False, remaining, cooldown_until

    return True, remaining, None


def get_or_create_device_id(request):
    """
    Récupère l'identifiant unique de l'appareil depuis le cookie sécurisé ou génère un UUID.
    Retourne (device_id, is_new).
    """
    device_id = request.COOKIES.get("ax_device_id")
    is_new = False
    if not device_id or len(device_id) < 16:
        import uuid
        device_id = uuid.uuid4().hex
        is_new = True
    return device_id, is_new


def parse_device_info(user_agent_str):
    """
    Déduit un libellé clair et ergonomique de l'appareil depuis le User-Agent :
    Ex: 'Chrome sur Android', 'Safari sur iPhone', 'Chrome sur Windows', etc.
    """
    ua = (user_agent_str or "").lower()

    # Système d'exploitation
    if "iphone" in ua:
        os_name = "iPhone"
    elif "ipad" in ua:
        os_name = "iPad"
    elif "android" in ua:
        os_name = "Android"
    elif "windows" in ua:
        os_name = "Windows"
    elif "macintosh" in ua or "mac os" in ua:
        os_name = "Mac"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Appareil"

    # Navigateur
    if "edg" in ua:
        browser_name = "Edge"
    elif "samsungbrowser" in ua:
        browser_name = "Samsung Internet"
    elif "chrome" in ua and "chromium" not in ua and "edg" not in ua:
        browser_name = "Chrome"
    elif "safari" in ua and "chrome" not in ua:
        browser_name = "Safari"
    elif "firefox" in ua:
        browser_name = "Firefox"
    elif "opera" in ua or "opr" in ua:
        browser_name = "Opera"
    else:
        browser_name = "Navigateur"

    return f"{browser_name} sur {os_name}"
