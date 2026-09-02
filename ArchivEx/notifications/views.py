from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Notification


@login_required
def notification_list(request):
    """Liste de toutes les notifications de l'utilisateur avec filtrage par catégorie."""
    notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")

    filter_type = request.GET.get("filter", "")
    if filter_type == "unread":
        notifications = notifications.filter(is_read=False)
    elif filter_type in ["NEW_EXAM", "NEW_CORRECTION", "NEW_SUMMARY", "NEW_GUIDE", "NEW_ADVICE", "PAYMENT", "SYSTEM", "NEW_SUPPORT", "SUPPORT_REPLY"]:
        notifications = notifications.filter(notification_type=filter_type)

    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()

    context = {
        "notifications": notifications,
        "unread_count": unread_count,
        "selected_filter": filter_type,
    }
    return render(request, "notifications/list.html", context)


@login_required
def mark_notification_read(request, pk):
    """Marque une notification comme lue et redirige vers sa ressource cible."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return JsonResponse({"status": "ok", "unread_count": unread_count})

    if notification.link and notification.link.strip():
        return redirect(notification.link)

    return redirect("notifications:list")


@login_required
def mark_all_read(request):
    """Marque toutes les notifications de l'utilisateur comme lues."""
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok", "unread_count": 0})

    return redirect("notifications:list")

