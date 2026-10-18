"""Voice calls (M14: VOICE-01, 02, 16 … 18; COMP-02 … 04; SEC-13). Panels, the REST API, telephony webhooks, the
Voice Gateway and the scheduler all call these functions.

Outbound calls pass the compliance checks before every dial (consent / Do-not-call, allowed countries, calling
window, attempt caps, daily cap, plan limits). Every number, cap and window is a setting (System Settings → Calling;
a company may only tighten them) or plan data — nothing is hard-coded.
"""

import hashlib
import hmac
import math
import threading
import urllib.parse
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.agents.models import AIEmployee, Conversation, UsageEvent
from apps.agents.tools import company_tz
from apps.audit.services import record
from apps.billing import limits
from apps.core.india import normalise_phone
from apps.crm import services as crm
from apps.platform_config.services import get as setting
from apps.providers.adapters import ProviderError
from apps.providers.services import production
from apps.tenancy.context import company_context, platform_context

from . import telephony
from .models import Call, PhoneNumber


class CallBlocked(ValidationError):
    """An outbound call may not be placed now; `retry_at` is set when it may be placed later (calling window)."""

    def __init__(self, message, retry_at=None):
        super().__init__(message)
        self.retry_at = retry_at


# ------------------------------------------------------------------ signed URLs (webhooks, media stream)
def _sign(text):
    return hmac.new(settings.SECRET_KEY.encode(), text.encode(), hashlib.sha256).hexdigest()[:32]


def webhook_token(provider):
    return _sign(f"telephony:{provider.key}")


def webhook_url(provider, action, **query):
    url = f"{settings.PUBLIC_BASE_URL}/webhooks/telephony/{provider.key}/{webhook_token(provider)}/{action}/"
    return url + ("?" + urllib.parse.urlencode(query) if query else "")


def media_token(call_id):
    return _sign(f"media:{call_id}")


def stream_params(call, mode="talk"):
    return {"call": str(call.pk), "sig": media_token(call.pk), "mode": mode}


def stream_url(call):
    return f"{settings.VOICE_GATEWAY_URL}/media/{call.provider.vendor if call.provider else 'browser'}"


# ------------------------------------------------------------------ company policy (CP-06: tighten only)
POLICY_KEYS = {
    "window_start": ("calling.window_start", max),
    "window_end": ("calling.window_end", min),
    "max_attempts_per_lead_per_day": ("calling.max_attempts_per_lead_per_day", min),
    "max_attempts_per_lead": ("calling.max_attempts_per_lead", min),
    "max_calls_per_day": ("calling.max_calls_per_day", min),
    "recordings_days": ("retention.recordings_days", min),
    "transcripts_days": ("retention.transcripts_days", min),
}


def policy(company):
    """Effective calling rules: the platform setting, or the company's stricter value."""
    own = (company.settings or {}).get("calling") or {}
    out = {}
    for key, (setting_key, stricter) in POLICY_KEYS.items():
        platform = setting(setting_key)
        out[key] = stricter(platform, own[key]) if own.get(key) not in (None, "") else platform
    out["recording_enabled"] = own.get("recording_enabled", setting("calling.recording_enabled_default"))
    return out


def save_policy(company, data, user=None, request=None):
    """The company's own calling rules — each must stay within the platform limit."""
    own = {}
    for key, (setting_key, stricter) in POLICY_KEYS.items():
        value = data.get(key)
        if value in (None, ""):
            continue
        if key.startswith("window"):
            value = str(value)[:5]
            if len(value) != 5 or value[2] != ":":
                raise ValidationError("Use the 24-hour format HH:MM.")
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValidationError(f"{key.replace('_', ' ').capitalize()}: enter a number.") from None
            if value < 1:
                raise ValidationError(f"{key.replace('_', ' ').capitalize()}: must be at least 1.")
        platform = setting(setting_key)
        if stricter(platform, value) != value:
            raise ValidationError(
                f"{key.replace('_', ' ').capitalize()} can be at most as wide as the platform limit ({platform})."
            )
        own[key] = value
    if own.get("window_start") and own.get("window_end") and own["window_start"] >= own["window_end"]:
        raise ValidationError("The calling window must end after it starts.")
    if "recording_enabled" in data:
        own["recording_enabled"] = bool(data["recording_enabled"])
    company.settings = {**(company.settings or {}), "calling": own}
    company.save(update_fields=["settings", "updated_at"])
    record(request, "calling_policy.update", "company", str(company.pk), own, user, company=company)
    return policy(company)


# ------------------------------------------------------------------ phone numbers (VOICE-16)
def clean_e164(value):
    e164 = normalise_phone(str(value or ""))
    if not (e164.startswith("+") and e164[1:].isdigit() and 8 <= len(e164) <= 16):
        raise ValidationError("Enter the number in international format, e.g. +918045678901.")
    return e164


def save_number(number, data, user=None, request=None):
    """Super Admin number pool: provider, number, capabilities and which company it belongs to."""
    from apps.providers.models import Provider
    from apps.tenancy.models import Company

    creating = number is None
    number = number or PhoneNumber()
    if "provider" in data:
        ref = str(data["provider"])
        provider = Provider.objects.filter(key=ref).first() or Provider.objects.filter(pk=_uuid(ref)).first()
        if not provider or "telephony" not in provider.capabilities:
            raise ValidationError("Choose a telephony provider.")
        number.provider = provider
    if "e164" in data:
        number.e164 = clean_e164(data["e164"])
        if PhoneNumber.objects.exclude(pk=number.pk).filter(e164=number.e164).exists():
            raise ValidationError("This number is already in the pool.")
    for f in ("label", "provider_number_id"):
        if f in data:
            setattr(number, f, str(data[f] or "").strip())
    if "capabilities" in data:
        caps = [c for c in data["capabilities"] or [] if c in dict(PhoneNumber.CAPABILITIES)]
        if not caps:
            raise ValidationError("Choose inbound, outbound or both.")
        number.capabilities = caps
    for f in ("is_test",):
        if f in data:
            setattr(number, f, bool(data[f]))
    if "status" in data:
        if data["status"] not in (PhoneNumber.ACTIVE, PhoneNumber.INACTIVE):
            raise ValidationError("Unknown status.")
        number.status = data["status"]
    if "company" in data:
        company = Company.objects.filter(pk=_uuid(str(data["company"] or ""))).first() if data["company"] else None
        if data["company"] and not company:
            raise ValidationError("Unknown company.")
        if (company and company.pk) != number.company_id:
            number.company, number.employee = company, None  # a new owner connects it to its own AI Employee
    if not number.provider_id or not number.e164:
        raise ValidationError("Provider and number are required.")
    if not number.capabilities:
        number.capabilities = [c for c, _ in PhoneNumber.CAPABILITIES]
    number.save()
    record(
        request,
        "phone_number.create" if creating else "phone_number.update",
        "phone_number",
        number.e164,
        {"company": str(number.company_id or ""), "status": number.status},
        user,
    )
    return number


def delete_number(number, user=None, request=None):
    if Call.all_companies.filter(phone_number=number).exists():
        raise ValidationError("Calls were made with this number — switch it off instead of deleting it.")
    record(request, "phone_number.delete", "phone_number", number.e164, user=user)
    number.delete()


def numbers_for(company):
    return PhoneNumber.objects.filter(company=company).select_related("provider", "employee")


def connect_number(company, number, employee, user=None, request=None):
    """EMP-08: the company connects one of its numbers to an AI Employee (inbound routing), or disconnects it."""
    if number.company_id != company.pk:
        raise ValidationError("This number does not belong to your company.")
    if employee is not None and employee.company_id != company.pk:
        raise ValidationError("Unknown AI Employee.")
    number.employee = employee
    number.save(update_fields=["employee", "updated_at"])
    record(
        request,
        "phone_number.connect",
        "phone_number",
        number.e164,
        {"employee": str(employee.pk) if employee else ""},
        user,
        company=company,
    )
    return number


def number_for(employee, capability):
    return (
        PhoneNumber.objects.filter(employee=employee, company_id=employee.company_id, status=PhoneNumber.ACTIVE)
        .select_related("provider")
        .filter(capabilities__contains=[capability])
        .first()
    )


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ------------------------------------------------------------------ limits & compliance (VOICE-18, COMP-02 … 04)
def _day_start(company, now):
    local = timezone.localtime(now, company_tz(company))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(company, now):
    return _day_start(company, now).replace(day=1)


def live_calls(company):
    return Call.objects.filter(company=company, status__in=Call.LIVE).count()


def check_capacity(company, now=None):
    """Plan limits that apply to inbound and outbound calls: concurrent calls, calls and voice minutes per month."""
    now = now or timezone.now()
    limits.check(company, "concurrent_calls", live_calls(company), label="concurrent calls")
    month = Call.objects.filter(company=company, queued_at__gte=_month_start(company, now))
    limits.check(company, "calls", month.exclude(status=Call.CANCELED).count(), label="calls this month")
    seconds = month.aggregate(s=Sum("duration_sec"))["s"] or 0
    cap = limits.limit(company, "voice_minutes")
    if cap is not None and seconds / 60 >= cap:
        raise ValidationError(f"Your plan's {cap} voice minutes for this month are used up.")


def next_window_start(company, now):
    local = timezone.localtime(now, company_tz(company))
    start = datetime.strptime(policy(company)["window_start"], "%H:%M").time()
    candidate = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    return candidate if candidate > local else candidate + timedelta(days=1)


def check_outbound(employee, lead, now=None):
    """→ the PhoneNumber to call from; raises CallBlocked with the reason otherwise."""
    now = now or timezone.now()
    company = employee.company
    rules = policy(company)
    if employee.status != AIEmployee.ACTIVE:
        raise CallBlocked(f"{employee.name} is not active.")
    number = number_for(employee, "outbound")
    if not number:
        raise CallBlocked(f"Connect a phone number for outbound calls to {employee.name} first.")
    if not number.provider.is_active or (production() and number.provider.test_only):
        raise CallBlocked(f"The telephony provider {number.provider.name} is switched off.")
    if lead is None or not lead.phone:
        raise CallBlocked("This lead has no phone number.")
    if not any(lead.phone.startswith(code) for code in setting("calling.allowed_country_codes")):
        raise CallBlocked("Calls to this country are not allowed.")
    if setting("calling.dnd_check_enabled") and (lead.dnd or lead.consent_status == "opted_out"):
        raise CallBlocked("The customer has opted out of calls (Do not call).")
    local = timezone.localtime(now, company_tz(company)).strftime("%H:%M")
    if not (rules["window_start"] <= local < rules["window_end"]):
        raise CallBlocked(
            f"Outbound calls are allowed between {rules['window_start']} and {rules['window_end']}.",
            retry_at=next_window_start(company, now),
        )
    outbound = Call.objects.filter(company=company, lead=lead, direction="outbound").exclude(status=Call.CANCELED)
    outbound = outbound.exclude(status=Call.QUEUED, provider_call_id="")  # not dialled yet
    if outbound.filter(queued_at__gte=_day_start(company, now)).count() >= rules["max_attempts_per_lead_per_day"]:
        raise CallBlocked(
            "This lead was already called the maximum number of times today.",
            retry_at=next_window_start(company, _day_start(company, now) + timedelta(days=1)),
        )
    if outbound.count() >= rules["max_attempts_per_lead"]:
        raise CallBlocked("This lead was already called the maximum number of times.")
    today = Call.objects.filter(company=company, direction="outbound", queued_at__gte=_day_start(company, now))
    if today.exclude(status=Call.CANCELED).count() >= rules["max_calls_per_day"]:
        raise CallBlocked("Your company reached today's call limit.")
    try:
        check_capacity(company, now)
    except ValidationError as exc:
        raise CallBlocked(exc.messages[0]) from None
    return number


# ------------------------------------------------------------------ placing calls (VOICE-02)
def place_call(employee, lead, reason="call_now", user=None, request=None):
    """Authorised outbound call: compliance first, then the provider dials; the media stream joins on answer."""
    number = check_outbound(employee, lead)
    call = Call.objects.create(
        company=employee.company,
        employee=employee,
        lead=lead,
        phone_number=number,
        provider=number.provider,
        direction="outbound",
        reason=reason,
        from_e164=number.e164,
        to_e164=lead.phone,
        requested_by=user if user and user.is_authenticated else None,
        events=[_event(Call.QUEUED, reason)],
    )
    _dial(call)
    record(
        request,
        "call.place",
        "call",
        str(call.pk),
        {"lead": str(lead.pk), "reason": reason},
        user,
        company=call.company,
    )
    return call


def _dial(call):
    adapter = telephony.for_provider(call.provider, timeout=setting("ai.request_timeout_seconds"))
    try:
        call.provider_call_id = adapter.place_call(
            call.to_e164,
            call.from_e164,
            webhook_url(call.provider, "answer", call=call.pk),
            webhook_url(call.provider, "status", call=call.pk),
            setting("calling.ring_timeout_seconds"),
            employee_max_minutes(call.employee) * 60,
            amd=True,
        )
        call.next_retry_at = None
        call.events = [*call.events, _event("dialled", call.provider_call_id)]
        call.save(update_fields=["provider_call_id", "next_retry_at", "events", "updated_at"])
    except ProviderError as exc:
        call.error = str(exc)[:500]
        transition(call, Call.FAILED, str(exc)[:200])
        finish(call)


def employee_max_minutes(employee):
    own = (employee.rules or {}).get("max_call_minutes")
    platform = setting("calling.max_call_minutes")
    return min(own, platform) if own else platform


def cancel(call, user=None, request=None):
    if call.status != Call.QUEUED:
        raise ValidationError("Only a call that has not started yet can be cancelled.")
    transition(call, Call.CANCELED, "cancelled by user")
    record(request, "call.cancel", "call", str(call.pk), user=user, company=call.company)
    return call


# ------------------------------------------------------------------ state machine (SDD §9.6)
def _event(status, detail=""):
    return {"at": timezone.now().isoformat(), "status": status, "detail": str(detail)[:200]}


def transition(call, status, detail=""):
    """Move the call to `status` when the state machine allows it. Returns True when it changed."""
    if not status or status == call.status:
        return False
    if status not in Call.TRANSITIONS.get(call.status, set()):
        call.events = [*call.events, _event(f"ignored:{status}", detail)]
        call.save(update_fields=["events", "updated_at"])
        return False
    now = timezone.now()
    call.status = status
    call.events = [*call.events, _event(status, detail)]
    if status == Call.IN_PROGRESS and not call.answered_at:
        call.answered_at = now
    if status in Call.TERMINAL and not call.ended_at:
        call.ended_at = now
    call.save()
    return True


def find_call(provider, event, call_id=None):
    """The call a provider callback belongs to (platform-wide lookup; webhooks carry no company)."""
    with platform_context():
        if call_id:
            call = Call.all_companies.filter(pk=_uuid(str(call_id)), provider=provider).first()
            if call:
                return call
        if event.get("call_id"):
            return Call.all_companies.filter(provider=provider, provider_call_id=event["call_id"]).first()
    return None


def apply_event(call, event):
    """A normalised provider status callback."""
    with company_context(call.company_id):
        if event.get("call_id") and not call.provider_call_id:
            call.provider_call_id = event["call_id"]
        if event.get("answered_by"):
            call.amd_result = event["answered_by"]
        if event.get("duration"):
            call.duration_sec = event["duration"]
        call.save()
        status = event.get("status")
        if status == Call.COMPLETED and call.amd_result == "machine" and call.direction == "outbound":
            status = Call.VOICEMAIL if call.status in (Call.RINGING, Call.IN_PROGRESS) else status
        transition(call, status, "provider")
        if call.status in Call.TERMINAL:
            finish(call)
    return call


def inbound(provider, event):
    """VOICE-01: a call to one of our numbers → the AI Employee connected to it, or None (not routed)."""
    with platform_context():
        number = (
            PhoneNumber.objects.filter(
                provider=provider, e164=normalise_phone(event.get("to") or ""), status=PhoneNumber.ACTIVE
            )
            .filter(capabilities__contains=["inbound"])
            .select_related("company", "employee")
            .first()
        )
    if not number or not number.company_id or not number.employee_id:
        return None
    employee, company = number.employee, number.company
    if company.status in ("suspended", "rejected", "pending") or employee.status != AIEmployee.ACTIVE:
        return None
    with company_context(company.id):
        try:
            check_capacity(company)
        except ValidationError:
            return None
        lead = crm.Lead.objects.filter(
            company=company, phone=normalise_phone(event.get("from") or ""), deleted_at__isnull=True
        ).first()
        return Call.objects.create(
            company=company,
            employee=employee,
            lead=lead,
            phone_number=number,
            provider=provider,
            provider_call_id=event.get("call_id", ""),
            direction="inbound",
            reason="inbound",
            from_e164=normalise_phone(event.get("from") or ""),
            to_e164=number.e164,
            status=Call.RINGING,
            events=[_event(Call.RINGING, "inbound")],
        )


# ------------------------------------------------------------------ after the call (REC-01, USE-01, VOICE-17)
def finish(call):
    """Runs once when a call reaches a final state: duration, usage, lead timeline, retry; the conversation's
    summary / extraction / score run in the background (they call the AI)."""
    if any(e.get("status") == "finished" for e in call.events):
        return
    if not call.duration_sec and call.answered_at and call.ended_at:
        call.duration_sec = int((call.ended_at - call.answered_at).total_seconds())
    call.billable_sec = call.duration_sec
    call.events = [*call.events, _event("finished")]
    call.save()
    minutes = math.ceil(call.duration_sec / 60) if call.duration_sec else 0
    common = {"company_id": call.company_id, "employee": call.employee, "conversation": call.conversation}
    rows = [UsageEvent(meter="calls", quantity=1, unit="calls", task=call.direction, **common)]
    if minutes:
        rows.append(UsageEvent(meter=f"voice_minutes_{call.direction}", quantity=minutes, unit="minutes", **common))
    UsageEvent.objects.bulk_create(rows)
    if call.lead_id:
        lead = call.lead
        lead.last_contact_at = call.ended_at or timezone.now()
        lead.save(update_fields=["last_contact_at", "updated_at"])
        length = f" · {call.duration_sec // 60}m {call.duration_sec % 60}s" if call.duration_sec else ""
        crm.log(
            lead,
            "call",
            f"{call.get_direction_display()} call by {call.employee.name} · {call.get_status_display()}{length}",
            actor_type="ai",
            call=str(call.pk),
        )
    schedule_retry(call)
    if call.conversation_id and call.conversation.status == Conversation.ACTIVE:
        _later(call.company_id, _end_conversation, call.conversation_id)


def _end_conversation(conversation_id):
    from apps.agents import runtime

    conv = Conversation.objects.filter(pk=conversation_id).first()
    if conv:
        runtime.end(conv)


def _later(company_id, fn, *args):
    if getattr(settings, "VOICE_INLINE", False):
        with company_context(company_id):
            fn(*args)
        return

    def run():
        try:
            with company_context(company_id):
                fn(*args)
        finally:
            close_old_connections()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())


def schedule_retry(call):
    """VOICE-17: busy / no answer / voicemail → another attempt after the configured gap, within the caps."""
    if call.direction != "outbound" or not call.lead_id or call.reason == "browser_test":
        return None
    if call.status not in setting("calling.retry_outcomes"):
        return None
    rules = policy(call.company)
    tried = Call.objects.filter(company=call.company, lead=call.lead, direction="outbound").exclude(
        status=Call.CANCELED
    )
    if tried.count() >= rules["max_attempts_per_lead"]:
        return None
    return Call.objects.create(
        company=call.company,
        employee=call.employee,
        lead=call.lead,
        phone_number=call.phone_number,
        provider=call.provider,
        direction="outbound",
        reason="retry",
        from_e164=call.from_e164,
        to_e164=call.to_e164,
        attempt=call.attempt + 1,
        retry_of=call,
        next_retry_at=timezone.now() + timedelta(minutes=setting("calling.retry_gap_minutes")),
        events=[_event(Call.QUEUED, f"retry after {call.status}")],
    )


def schedule_follow_up(employee, lead, when, user=None):
    """A follow-up call at a set time (dialled by the scheduler through the same checks)."""
    return Call.objects.create(
        company=employee.company,
        employee=employee,
        lead=lead,
        direction="outbound",
        reason="follow_up",
        to_e164=lead.phone,
        next_retry_at=when,
        requested_by=user if user and user.is_authenticated else None,
        events=[_event(Call.QUEUED, "follow-up scheduled")],
    )


def dial_due(now=None):
    """Scheduler (cron, every minute): dial queued retries / follow-ups that are due. Calls blocked by the calling
    window move to the next window; other blocks cancel the call with the reason."""
    now = now or timezone.now()
    done = 0
    with platform_context():
        due = list(
            Call.all_companies.filter(status=Call.QUEUED, provider_call_id="", next_retry_at__lte=now).values_list(
                "pk", "company_id"
            )
        )
    for pk, company_id in due:
        with company_context(company_id):
            call = Call.objects.select_related("employee", "lead", "company").get(pk=pk)
            try:
                number = check_outbound(call.employee, call.lead, now)
            except CallBlocked as exc:
                if exc.retry_at:
                    call.next_retry_at = exc.retry_at
                    call.events = [*call.events, _event("postponed", exc.messages[0])]
                    call.save(update_fields=["next_retry_at", "events", "updated_at"])
                else:
                    call.error = exc.messages[0]
                    transition(call, Call.CANCELED, exc.messages[0])
                continue
            call.phone_number, call.provider, call.from_e164 = number, number.provider, number.e164
            call.save(update_fields=["phone_number", "provider", "from_e164", "updated_at"])
            _dial(call)
            done += 1
    return done
