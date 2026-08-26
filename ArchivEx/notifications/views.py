from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Notification


@login_required
def notification_list(request):
    """Liste de toutes les notifications de l'utilisateur."""
    user_notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")

    context = {
        "notifications": user_notifications,
    }
    return render(request, "notifications/list.html", context)


@login_required
def mark_notification_read(request, pk):
    """Marque une notification comme lue."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok"})

    if notification.link:
        return redirect(notification.link)
    return redirect("notifications:list")


@login_required
def mark_all_read(request):
    """Marque toutes les notifications de l'utilisateur comme lues."""
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok"})

    return redirect("notifications:list")
