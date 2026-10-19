"""CP-03 / NOTI-02 / NOTI-03: alerts to the company's people — transfer requests, hot leads, bookings, finished
campaigns and usage alerts.

Every alert is a Notification (the bell / notification centre, read and unread). Copies go out on the channels each
person chose in Profile → Alerts (platform default: System Settings → Notifications): e-mail (the kind's template in
Email Templates), WhatsApp (the company's approved "Team alert" template) and push (installed web app / mobile app).
"""

import logging
import threading

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections, transaction

from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context

from . import push
from . import services as mail
from .models import Notification

log = logging.getLogger(__name__)
RUN_INLINE = False  # tests deliver at once; the server delivers in a thread once the change is saved

KINDS = dict(Notification.KINDS)
CHANNELS = [("in_app", "In the panel"), ("email", "E-mail"), ("whatsapp", "WhatsApp"), ("push", "Push")]
OPTIONAL = ("email", "whatsapp", "push")  # the bell always gets the alert


def clean_channels(values):
    values = values.replace(",", "\n").splitlines() if isinstance(values, str) else values or []
    known = {c for c, _ in CHANNELS}
    out = [str(v).strip() for v in values if str(v).strip()]
    bad = [v for v in out if v not in known]
    if bad:
        raise ValidationError(f"Unknown channel {bad[0]!r}: use {', '.join(sorted(known))}.")
    return list(dict.fromkeys(out))


def channels_for(user, kind):
    """The person's own choice for this kind, or the platform default."""
    own = ((user.notification_prefs or {}).get("alerts") or {}).get(kind)
    chosen = own if isinstance(own, list) else setting("notifications.default_channels")
    return [c for c in chosen if c in OPTIONAL]


def prefs(user):
    """{kind: {channel: on}} for the profile page and the API."""
    return {k: {c: c in channels_for(user, k) for c in OPTIONAL} for k in KINDS}


def save_prefs(user, data):
    """data {kind: [channels]} — only the kinds given change."""
    alerts = dict((user.notification_prefs or {}).get("alerts") or {})
    for kind, chosen in (data or {}).items():
        if kind not in KINDS:
            raise ValidationError(f"Unknown alert {kind!r}.")
        alerts[kind] = [c for c in clean_channels(chosen) if c in OPTIONAL]
    user.notification_prefs = {**(user.notification_prefs or {}), "alerts": alerts}
    user.save(update_fields=["notification_prefs"])
    return prefs(user)


def people_with(company, perm):
    """Active members of the company who hold `perm` (e.g. the managers who should hear about unassigned hot leads)."""
    from apps.crm.services import members
    from apps.rbac.services import has_perm

    return [u for u in members(company) if has_perm(u, perm, company)]


# ------------------------------------------------------------------ delivery
def _whatsapp(company, user, text):
    from apps.whatsapp import services as whatsapp

    if not user.phone:
        raise ValidationError("No mobile number in the person's profile.")
    return whatsapp.send_alert(company, user.phone, text)


def _deliver(pk, email):
    note = Notification.objects.select_related("user", "company").get(pk=pk)
    user, done = note.user, {}
    for channel in channels_for(user, note.kind):
        try:
            if channel == "email":
                if not (email and user.email):
                    raise ValidationError("No e-mail for this alert.")
                key, context = email
                context = {
                    "name": user.full_name or user.email,
                    "url": f"{settings.PUBLIC_BASE_URL}{note.url}",
                    "company_name": note.company.name,
                    **context,
                }
                if not mail.send(key, user.email, context):
                    raise ValidationError("E-mail template switched off.")
            elif channel == "push":
                if not user.devices.exists():
                    raise ValidationError("No device has push switched on (Profile → Alerts).")
                push.send(
                    user, {"title": note.title, "body": note.body, "url": note.url, "kind": note.kind, "id": str(pk)}
                )
            elif channel == "whatsapp":
                if not setting("notifications.whatsapp_enabled"):
                    raise ValidationError("WhatsApp alerts are switched off for the platform.")
                _whatsapp(note.company, user, f"{note.title}. {note.body}".strip()[:900])
            done[channel] = "sent"
        except ValidationError as exc:
            done[channel] = f"skipped: {exc.messages[0]}"
        except Exception as exc:  # noqa: BLE001 — provider / mail server error: kept on the alert
            log.warning("alert %s on %s failed: %s", pk, channel, exc)
            done[channel] = f"failed: {str(exc)[:200]}"
    note.delivery = done
    note.save(update_fields=["delivery", "updated_at"])
    return done


def _run(company_id, pk, email):
    try:
        with company_context(company_id):
            _deliver(pk, email)
    except Exception:  # noqa: BLE001 — a failed alert never breaks the change that caused it
        log.exception("alert delivery failed")


def _thread(*args):
    try:
        _run(*args)
    finally:
        connections.close_all()


def notify(company, users, kind, title, body="", url="", email=None, data=None, wait=False):
    """One alert per person (the bell), then e-mail / WhatsApp / push copies after the change is saved.
    email: (template key, context). wait=True delivers now and returns {user id: delivery} (callers in a thread)."""
    out, seen = [], set()
    for user in users:
        if not user or user.pk in seen or not user.is_active:
            continue
        seen.add(user.pk)
        note = Notification.objects.create(
            company=company,
            user=user,
            kind=kind,
            title=title[:200],
            body=(body or "")[:500],
            url=url[:500],
            data=data or {},
        )
        args = (company.pk, note.pk, email)
        if wait:
            note.delivery = _deliver(note.pk, email)
        elif RUN_INLINE:
            _run(*args)
        else:  # ponytail: a thread per alert; move to a worker queue when there is one
            transaction.on_commit(lambda a=args: threading.Thread(target=_thread, args=a, daemon=True).start())
        out.append(note)
    return out


# ------------------------------------------------------------------ the bell (NOTI-02)
def unread_count(user, company):
    return Notification.objects.filter(company=company, user=user, read_at__isnull=True).count()


def mark_read(user, company, ids=None):
    from django.utils import timezone

    qs = Notification.objects.filter(company=company, user=user, read_at__isnull=True)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs.update(read_at=timezone.now())
