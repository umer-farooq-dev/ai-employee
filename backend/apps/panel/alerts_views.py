"""NOTI-02 / CP-03: the notification centre (the bell's full list)."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.notifications import alerts
from apps.notifications.models import Notification

from .company_views import company_perm


@company_perm("company.view")
def notifications(request):
    qs = Notification.objects.filter(company=request.company, user=request.user)
    if request.method == "POST":
        alerts.mark_read(request.user, request.company)
        messages.success(request, "All alerts marked as read.")
        return redirect("panel:notifications")
    unread = request.GET.get("show") == "unread"
    if unread:
        qs = qs.filter(read_at__isnull=True)
    if request.GET.get("kind") in alerts.KINDS:
        qs = qs.filter(kind=request.GET["kind"])
    return render(
        request,
        "panel/company/notifications.html",
        {
            "page": Paginator(qs, 25).get_page(request.GET.get("page")),
            "unread": unread,
            "kind": request.GET.get("kind", ""),
            "kinds": alerts.KINDS,
            "unread_count": alerts.unread_count(request.user, request.company),
        },
    )


@company_perm("company.view")
def open_notification(request, pk):
    """From the bell, the list or a push alert: mark read and go to what it is about (panel links only)."""
    note = get_object_or_404(Notification, pk=pk, company=request.company, user=request.user)
    if not note.read_at:
        note.read_at = timezone.now()
        note.save(update_fields=["read_at", "updated_at"])
    safe = url_has_allowed_host_and_scheme(note.url, allowed_hosts={request.get_host()}) and note.url.startswith("/")
    return redirect(note.url if safe else "panel:notifications")
