"""Company panel: Support (CP-05) — raise a ticket to the platform team and follow the conversation."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.storage import signed_url
from apps.platform_config.services import get as setting
from apps.support import services as support
from apps.support.models import Ticket

from .company_views import _errors, company_perm


@company_perm("company.view")
def tickets(request):
    company = request.company
    if request.method == "POST":
        try:
            ticket = support.open_ticket(company, request.user, request.POST, request.FILES.get("file"), request)
            messages.success(request, f"Ticket {ticket.number} sent. We reply by e-mail and here.")
            return redirect("panel:support_ticket", pk=ticket.pk)
        except ValidationError as exc:
            _errors(request, exc)
    qs = Ticket.objects.filter(company=company).select_related("created_by")
    status = request.GET.get("status", "")
    if status == "open":
        qs = qs.exclude(status__in=(Ticket.RESOLVED, Ticket.CLOSED))
    elif status == "closed":
        qs = qs.filter(status__in=(Ticket.RESOLVED, Ticket.CLOSED))
    return render(
        request,
        "panel/company/support/list.html",
        {
            "tickets": qs,
            "status": status,
            "categories": setting("support.categories"),
            "priorities": Ticket.PRIORITIES,
            "values": request.POST if request.method == "POST" else {},
            "contact": {
                "email": setting("contact.support_email"),
                "phone": setting("contact.support_phone"),
                "whatsapp": setting("contact.whatsapp"),
            },
        },
    )


@company_perm("company.view")
def ticket(request, pk):
    t = get_object_or_404(Ticket, pk=pk, company=request.company)
    if request.method == "POST":
        try:
            if request.POST.get("op") == "close":
                support.set_status(t, Ticket.CLOSED, request.user, request)
                messages.success(request, "Ticket closed.")
            else:
                support.reply(t, request.user, request.POST.get("body"), request.FILES.get("file"), request=request)
                messages.success(request, "Reply sent.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:support_ticket", pk=pk)
    thread = [(m, signed_url(m.attachment_key) if m.attachment_key else "") for m in t.messages.filter(internal=False)]
    return render(request, "panel/company/support/ticket.html", {"t": t, "thread": thread})
