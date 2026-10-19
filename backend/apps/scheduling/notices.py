"""CAL-07 confirmations and reminders to the customer (approved WhatsApp template + e-mail) and CAL-10 e-mails to the
assigned person about new, moved and cancelled bookings.

Platform defaults are System Settings → Calendar; a company can set its own under Calendar → Messages. Every message
sent — or the reason it was not — is an AppointmentNotice, shown on the appointment page.
"""

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.services import record
from apps.notifications import services as mail
from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context, platform_context

from .models import Appointment, AppointmentNotice

log = logging.getLogger(__name__)
RUN_INLINE = False  # tests send at once; the server sends in a thread once the booking is saved

POLICY_KEYS = {
    "confirm_whatsapp": "calendar.confirm_whatsapp",
    "confirm_email": "calendar.confirm_email",
    "cancel_notice": "calendar.cancel_notice",
    "reminder_hours": "calendar.reminder_hours",
    "reminder_whatsapp": "calendar.reminder_whatsapp",
    "reminder_email": "calendar.reminder_email",
    "notify_staff": "calendar.notify_staff",
}
CHANNELS = ("whatsapp", "email")
EMAILS = {
    "confirmation": "appointment/confirmation",
    "rescheduled": "appointment/rescheduled",
    "cancelled": "appointment/cancelled",
    "reminder": "appointment/reminder",
}
PURPOSES = {
    "confirmation": "appointment_confirmation",
    "rescheduled": "appointment_confirmation",
    "cancelled": "appointment_cancelled",
    "reminder": "appointment_reminder",
}
EVENTS = {"booked": "confirmation", "rescheduled": "rescheduled", "cancelled": "cancelled"}


class Skip(Exception):
    """Not sent for a reason the team can fix (no address, no approved template, opted out …)."""


# ------------------------------------------------------------------ settings
def clean_hours(values, limit):
    if isinstance(values, str):
        values = values.replace(",", "\n").splitlines()
    out = set()
    for value in values or []:
        value = str(value).strip()
        if not value:
            continue
        try:
            hours = float(value)
        except ValueError:
            raise ValidationError(f"Reminder {value!r}: enter hours as a number, e.g. 24 or 0.5.") from None
        if not 0 < hours <= limit:
            raise ValidationError(f"Reminders must be more than 0 and at most {limit} hours before.")
        out.add(f"{hours:g}")
    return sorted(out, key=float, reverse=True)


def policy(company):
    """Effective messages for a company: its own choice, or the platform default."""
    own = (company.settings or {}).get("appointments") or {}
    return {key: own[key] if key in own else setting(skey) for key, skey in POLICY_KEYS.items()}


def save_policy(company, data, user=None, request=None):
    """Only the keys given change; {"use_platform": true} goes back to the platform defaults."""
    own = {} if data.get("use_platform") else dict((company.settings or {}).get("appointments") or {})
    for key in POLICY_KEYS:
        if key not in data or data.get("use_platform"):
            continue
        if key == "reminder_hours":
            own[key] = clean_hours(data[key], setting("calendar.reminder_max_hours"))
        else:
            own[key] = data[key] in (True, "true", "on", "1", 1)
    company.settings = {**(company.settings or {}), "appointments": own}
    company.save(update_fields=["settings", "updated_at"])
    record(request, "calendar.messages", "company", company.pk, own, user, company=company)
    return policy(company)


# ------------------------------------------------------------------ texts
def when_text(appt, start=None):
    from .services import tz_for

    return (start or appt.starts_at).astimezone(tz_for(appt.resource)).strftime("%A %d %b %Y, %I:%M %p")


def _context(appt, **extra):
    lead = appt.lead
    return {
        "lead_name": lead.name if lead else "",
        "lead_phone": lead.phone if lead else "",
        "lead_reference": lead.reference if lead else "",
        "company_name": appt.company.name,
        "appointment_type": appt.appointment_type.name,
        "appointment_number": appt.reference,
        "appointment_time": when_text(appt),
        "appointment_location": appt.location or appt.resource.name,
        "meeting_link": appt.meeting_link,
        "calendar_name": appt.resource.name,
        "appointment_url": f"{settings.PUBLIC_BASE_URL}{reverse('panel:appointment', args=[appt.pk])}",
        **extra,
    }


# ------------------------------------------------------------------ sending
def _email_opted_out(lead):
    from apps.crm.models import ConsentRecord

    last = (
        ConsentRecord.objects.filter(company_id=lead.company_id, lead=lead, channel__in=("email", "all"))
        .order_by("-created_at")
        .first()
    )
    return (last.action == "opt_out") if last else lead.consent_status == "opted_out"


def _whatsapp(appt, kind, lead):
    from apps.whatsapp import services as whatsapp

    if not lead.phone:
        raise Skip("The customer has no mobile number.")
    try:
        whatsapp.check_can_message(lead)
    except ValidationError as exc:
        raise Skip(exc.messages[0]) from None
    language = lead.preferred_language or appt.company.default_language or setting("locale.default_language")
    template = whatsapp.find_template(appt.company, PURPOSES[kind], language)
    if not template:
        raise Skip("No approved WhatsApp template for this (Settings → WhatsApp).")
    return whatsapp.send_template(template, lead, {"appointment": appt})


def _email(appt, kind, lead, extra):
    from apps.crm import services as crm

    if not lead.email:
        raise Skip("The customer has no e-mail address.")
    if _email_opted_out(lead):
        raise Skip("The customer opted out of e-mails.")
    if not mail.send(EMAILS[kind], lead.email, _context(appt, **extra)):
        raise Skip("This e-mail is switched off in Super Admin → Email Templates.")
    label = dict(AppointmentNotice.KINDS)[kind].lower()
    crm.log(lead, "email", f"Appointment {label} e-mailed: {appt.reference}", None, "system")
    return lead.email


def _to_customer(appt, kind, channels, offset=None, **extra):
    if not appt.lead_id:
        return []
    out = []
    for channel in channels:
        try:
            with transaction.atomic():
                note = AppointmentNotice.objects.create(
                    company_id=appt.company_id,
                    appointment=appt,
                    kind=kind,
                    channel=channel,
                    status=AppointmentNotice.SKIPPED,
                    offset_minutes=offset,
                    for_start=appt.starts_at,
                )
        except IntegrityError:  # nosec B112 — this reminder was already sent (the job ran twice)
            continue
        try:
            if channel == "whatsapp":
                note.recipient = appt.lead.phone
                note.wa_message = _whatsapp(appt, kind, appt.lead)
            else:
                note.recipient = _email(appt, kind, appt.lead, extra)
            note.status = AppointmentNotice.SENT
        except Skip as exc:
            note.detail = str(exc)[:255]
        except Exception as exc:  # noqa: BLE001 — provider or mail server error: logged on the notice
            log.warning("appointment %s %s on %s failed: %s", appt.pk, kind, channel, exc)
            note.status, note.detail = AppointmentNotice.FAILED, (getattr(exc, "messages", None) or [str(exc)])[0][:255]
        note.save(update_fields=["recipient", "wa_message", "status", "detail", "updated_at"])
        out.append(note)
    return out


TITLES = {"booked": "New booking", "rescheduled": "Booking moved", "cancelled": "Booking cancelled"}


def _to_staff(appt, event, actor_id, extra):
    """CAL-10 through the team alerts (bell, and e-mail / WhatsApp / push as the person chose)."""
    from apps.accounts.models import User
    from apps.notifications import alerts

    person = appt.assigned_user or appt.resource.user
    if not person or not person.is_active or person.pk == actor_id:
        return None
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    context = _context(
        appt,
        **extra,
        event=event,
        name=person.full_name or person.email,
        changed_by=(actor.full_name or actor.email) if actor else "",
    )
    who = (appt.lead.name or appt.lead.reference) if appt.lead_id else appt.resource.name
    alert = alerts.notify(
        appt.company,
        [person],
        "appointment",
        f"{TITLES[event]}: {appt.appointment_type.name} — {context['appointment_time']}",
        f"{who} · {appt.reference}"
        + (f" · {appt.cancel_reason}" if event == "cancelled" and appt.cancel_reason else ""),
        reverse("panel:appointment", args=[appt.pk]),
        email=("appointment/staff_notice", context),
        data={"appointment": str(appt.pk), "event": event},
        wait=True,
    )[0]
    result = alert.delivery.get("email", "skipped: E-mail alerts are off in this person's Profile → Alerts.")
    status = result.split(":")[0]
    return AppointmentNotice.objects.create(
        company_id=appt.company_id,
        appointment=appt,
        kind="staff",
        channel="email",
        recipient=person.email,
        for_start=appt.starts_at,
        status=status if status in dict(AppointmentNotice.STATUSES) else AppointmentNotice.SENT,
        detail="" if status == "sent" else result.split(":", 1)[-1].strip()[:255],
    )


def _changed(pk, event, actor_id, old_start):
    appt = Appointment.objects.select_related("company", "lead", "resource", "appointment_type").get(pk=pk)
    rules = policy(appt.company)
    extra = {"old_time": when_text(appt, old_start) if old_start else "", "reason": appt.cancel_reason}
    if event != "cancelled" or rules["cancel_notice"]:
        _to_customer(appt, EVENTS[event], [c for c in CHANNELS if rules[f"confirm_{c}"]], **extra)
    if rules["notify_staff"]:
        _to_staff(appt, event, actor_id, extra)


def _run(company_id, *args):
    try:
        with company_context(company_id):
            _changed(*args)
    except Exception:  # noqa: BLE001 — a failed message never breaks the booking
        log.exception("appointment messages failed")


def _thread(*args):
    try:
        _run(*args)
    finally:
        connections.close_all()  # this thread's own connections


def changed(appt, event, user=None, old_start=None):
    """After a booking is made, moved or cancelled: sent once the change is saved (never for a rolled-back one)."""
    args = (appt.company_id, appt.pk, event, user.pk if user and user.is_authenticated else None, old_start)
    if RUN_INLINE:
        transaction.on_commit(lambda: _run(*args))
    else:  # ponytail: a thread per booking; move to a worker queue when there is one
        transaction.on_commit(lambda: threading.Thread(target=_thread, args=args, daemon=True).start())


def resend(appt, user=None, request=None):
    """The team sends the confirmation again (e.g. after adding the customer's e-mail)."""
    if appt.status not in Appointment.ACTIVE:
        raise ValidationError("Only upcoming appointments can be confirmed again.")
    rules = policy(appt.company)
    channels = [c for c in CHANNELS if rules[f"confirm_{c}"]]
    if not channels:
        raise ValidationError("Confirmations are switched off (Calendar → Messages).")
    notes = _to_customer(appt, "confirmation", channels)
    record(request, "appointment.resend", "appointment", appt.pk, company=appt.company)
    return notes


# ------------------------------------------------------------------ reminders (cron)
def send_reminders(now=None):
    """Each upcoming appointment gets the latest reminder that is due, once per appointment time. Reminder times
    before the booking was made (or moved) are skipped, so a late booking does not get a 24-hour reminder."""
    now = now or timezone.now()
    horizon = now + timedelta(hours=setting("calendar.reminder_max_hours"))
    sent, rules = 0, {}
    with platform_context():
        qs = (
            Appointment.all_companies.filter(
                status__in=Appointment.ACTIVE, starts_at__gt=now, starts_at__lte=horizon, lead__isnull=False
            )
            .exclude(company__status="suspended")
            .exclude(company__deleted_at__isnull=False)
            .select_related("company", "lead", "resource", "appointment_type")
        )
        for appt in qs:
            p = rules.setdefault(appt.company_id, policy(appt.company))
            channels = [c for c in CHANNELS if p[f"reminder_{c}"]]
            since = appt.time_set_at or appt.created_at
            due = [
                round(float(h) * 60)
                for h in p["reminder_hours"] or []
                if since <= appt.starts_at - timedelta(hours=float(h)) <= now
            ]
            if not (channels and due):
                continue
            with company_context(appt.company_id):
                notes = _to_customer(appt, "reminder", channels, offset=min(due))
            sent += sum(n.status == AppointmentNotice.SENT for n in notes)
    return sent
