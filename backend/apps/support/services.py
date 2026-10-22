"""SA-19 / CP-05: a company raises a ticket, the platform team answers in Super Admin, both sides are e-mailed.
Categories and auto-close days are settings (System Settings → Support)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.services import record
from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context, platform_context

from .models import Ticket, TicketCounter, TicketMessage

T = Ticket


def _number():
    with transaction.atomic():
        row, _ = TicketCounter.objects.select_for_update().get_or_create(key="ticket")
        row.last += 1
        row.save(update_fields=["last", "updated_at"])
    return f"T-{row.last}"


def _attach(company, upload):
    if not upload:
        return "", ""
    from apps.core.storage import company_path, private_storage
    from apps.core.uploads import scan, validate_upload

    validate_upload(upload)
    data = upload.read()
    scan(data)
    from django.core.files.base import ContentFile

    key = private_storage.save(company_path(company.id, "support", upload.name), ContentFile(data))
    return key, upload.name[:255]


def _absolute(name, *args):
    from django.conf import settings

    return settings.PUBLIC_BASE_URL.rstrip("/") + reverse(name, args=args)


def _mail(key, to, context):
    from apps.notifications import services as mail

    for address in dict.fromkeys(a for a in to if a):
        mail.send(key, address, context)


def _team(ticket, text):
    """New ticket / company reply → the platform team inbox (General Settings → team notification e-mails)."""
    from apps.notifications.services import team_recipients

    url = _absolute("superadmin:ticket", ticket.pk)
    ctx = {
        "number": ticket.number,
        "subject": ticket.subject,
        "company_name": ticket.company.name,
        "priority": ticket.get_priority_display(),
        "text": text,
        "url": url,
    }
    transaction.on_commit(lambda: _mail("support/team", team_recipients(), ctx))


def open_ticket(company, user, data, upload=None, request=None):
    subject = str(data.get("subject", "")).strip()[:200]
    body = str(data.get("body", "")).strip()
    if not subject or not body:
        raise ValidationError("Write a subject and describe the problem.")
    category = str(data.get("category", "")).strip()
    if category and category not in setting("support.categories"):
        raise ValidationError("Choose a category from the list.")
    priority = data.get("priority") or "normal"
    if priority not in dict(T.PRIORITIES):
        raise ValidationError("Choose a priority.")
    key, name = _attach(company, upload)
    now = timezone.now()
    ticket = T.objects.create(
        company=company,
        number=_number(),
        subject=subject,
        category=category,
        priority=priority,
        created_by=user,
        last_reply_at=now,
    )
    TicketMessage.objects.create(
        company=company, ticket=ticket, author=user, body=body, attachment_key=key, attachment_name=name
    )
    record(request, "support.ticket_open", "ticket", ticket.id, company=company, user=user)
    _team(ticket, body)
    return ticket


def reply(ticket, user, body, upload=None, staff=False, internal=False, status=None, request=None):
    """A message on the ticket. Staff replies mark it answered and e-mail the company; company replies reopen it."""
    body = (body or "").strip()
    if not body:
        raise ValidationError("Write a message.")
    if ticket.status == T.CLOSED and not staff:
        raise ValidationError("This ticket is closed. Open a new ticket.")
    key, name = _attach(ticket.company, upload)
    msg = TicketMessage.objects.create(
        company=ticket.company,
        ticket=ticket,
        author=user,
        from_staff=staff,
        internal=internal and staff,
        body=body,
        attachment_key=key,
        attachment_name=name,
    )
    if not msg.internal:
        ticket.last_reply_at, ticket.last_reply_by_staff = msg.created_at, staff
        ticket.status = status or (T.ANSWERED if staff else T.WAITING)
        if ticket.status in (T.RESOLVED, T.CLOSED):
            ticket.closed_at = timezone.now()
        ticket.save()
        if staff:
            _notify_company(ticket, body)
        else:
            _team(ticket, body)
    elif status:
        set_status(ticket, status, user, request)
    record(request, "support.reply", "ticket", ticket.id, company=ticket.company, user=user)
    return msg


def _notify_company(ticket, body):
    from apps.notifications import alerts

    url = reverse("panel:support_ticket", args=[ticket.pk])
    people = [ticket.created_by] if ticket.created_by_id else []
    alerts.notify(
        ticket.company,
        people,
        "support",
        f"Support replied: {ticket.subject}"[:200],
        body[:300],
        url,
        email=(
            "support/reply",
            {"number": ticket.number, "subject": ticket.subject, "text": body, "status": ticket.get_status_display()},
        ),
    )


def set_status(ticket, status, user=None, request=None):
    if status not in dict(T.STATUSES):
        raise ValidationError("Unknown status.")
    ticket.status = status
    ticket.closed_at = timezone.now() if status in (T.RESOLVED, T.CLOSED) else None
    ticket.save(update_fields=["status", "closed_at", "updated_at"])
    record(
        request, "support.status", "ticket", ticket.id, company=ticket.company, user=user, changes={"status": status}
    )
    return ticket


def assign(ticket, staff_user, user=None, request=None):
    ticket.assigned_to = staff_user
    ticket.save(update_fields=["assigned_to", "updated_at"])
    record(request, "support.assign", "ticket", ticket.id, company=ticket.company, user=user)


def auto_close(now=None):
    """Answered / resolved tickets with no company reply for support.auto_close_days are closed (cron, daily)."""
    days = setting("support.auto_close_days")
    if not days:
        return 0
    cutoff = (now or timezone.now()) - timedelta(days=days)
    with platform_context():
        rows = list(
            T.all_companies.filter(status__in=(T.ANSWERED, T.RESOLVED), last_reply_at__lt=cutoff).values_list(
                "pk", "company_id"
            )
        )
    for pk, company_id in rows:
        with company_context(company_id):
            T.objects.filter(pk=pk).update(status=T.CLOSED, closed_at=timezone.now())
    return len(rows)
