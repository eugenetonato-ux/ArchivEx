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
        path = request.path if request else None
        ip_address = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '') if request else ''
        
        SiteLog.objects.create(
            user=user,
            action_type=action_type,
            description=description,
            path=path,
            ip_address=ip_address,
            user_agent=user_agent
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error creating SiteLog: {e}")
