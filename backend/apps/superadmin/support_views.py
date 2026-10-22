"""Super Admin: support tickets from companies (SA-19). Logic: apps.support.services."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.storage import signed_url
from apps.rbac.services import has_perm
from apps.support import services as support
from apps.support.models import Ticket
from apps.tenancy.context import company_context

from .views import _errors, page_of, staff_perm

OPEN = (Ticket.OPEN, Ticket.WAITING)


@staff_perm("tickets.view")
def tickets(request):
    qs = Ticket.all_companies.select_related("company", "created_by", "assigned_to")
    q, status, view = request.GET.get("q", "").strip(), request.GET.get("status", ""), request.GET.get("view", "")
    if status:
        qs = qs.filter(status=status)
    elif view != "all":
        qs = qs.exclude(status=Ticket.CLOSED)
    if view == "mine":
        qs = qs.filter(assigned_to=request.user)
    if request.GET.get("priority"):
        qs = qs.filter(priority=request.GET["priority"])
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(subject__icontains=q) | Q(company__name__icontains=q))
    counts = {
        "waiting": Ticket.all_companies.filter(status__in=OPEN).count(),
        "urgent": Ticket.all_companies.filter(status__in=OPEN, priority__in=("high", "urgent")).count(),
        "mine": Ticket.all_companies.filter(status__in=OPEN, assigned_to=request.user).count(),
    }
    return render(
        request,
        "panel/admin/support/list.html",
        {
            "page": page_of(request, qs.order_by("-last_reply_at")),
            "q": q,
            "status": status,
            "view": view,
            "statuses": Ticket.STATUSES,
            "priorities": Ticket.PRIORITIES,
            "counts": counts,
        },
    )


@staff_perm("tickets.view")
def ticket(request, pk):
    t = get_object_or_404(Ticket.all_companies.select_related("company", "created_by", "assigned_to"), pk=pk)
    can_manage = has_perm(request.user, "tickets.manage")
    with company_context(t.company_id):
        if request.method == "POST" and can_manage:
            op = request.POST.get("op")
            try:
                if op == "assign":
                    staff = get_user_model().objects.filter(pk=request.POST.get("user") or None, is_staff=True).first()
                    support.assign(t, staff, request.user, request)
                    messages.success(request, "Assigned.")
                elif op == "status":
                    support.set_status(t, request.POST.get("status"), request.user, request)
                    messages.success(request, "Status changed.")
                else:
                    internal = bool(request.POST.get("internal"))
                    support.reply(
                        t,
                        request.user,
                        request.POST.get("body"),
                        request.FILES.get("file"),
                        staff=True,
                        internal=internal,
                        status=request.POST.get("status") or None,
                        request=request,
                    )
                    messages.success(request, "Note saved." if internal else "Reply sent to the company.")
            except ValidationError as exc:
                _errors(request, exc)
            return redirect("superadmin:ticket", pk=pk)
        thread = [
            (m, signed_url(m.attachment_key) if m.attachment_key else "") for m in t.messages.select_related("author")
        ]
    return render(
        request,
        "panel/admin/support/ticket.html",
        {
            "t": t,
            "thread": thread,
            "statuses": Ticket.STATUSES,
            "staff": get_user_model().objects.filter(is_staff=True, is_active=True).order_by("email"),
            "can_manage": can_manage,
            "other": Ticket.all_companies.filter(company_id=t.company_id).exclude(pk=t.pk).order_by("-created_at")[:6],
        },
    )
