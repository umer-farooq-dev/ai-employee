"""WhatsApp (M15: WA-01 … WA-10, TOOL-09, COMP-07): numbers, templates, consent, the 24-hour customer service window,
inbound messages to the shared AI engine and the inbox, outbound messages and delivery tracking.

- A customer's message opens (or continues) a conversation of the AI Employee connected to the number. The AI answers
  unless a person has taken the chat over in the inbox (apps.agents.inbox) — the same rules as the website chat.
- Free-form replies are only possible inside the customer service window after the customer's last message (Meta's
  rule; the hours are a setting). Outside it only approved templates may be sent (WA-04).
- Opt-out keywords (STOP …) are honoured at once and stored as consent records (WA-08, COMP-02); templates go only to
  customers who did not opt out (and, by setting, who opted in).
"""

import logging
import re
import threading
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from apps.agents import inbox, runtime
from apps.agents.models import Conversation, Message, UsageEvent
from apps.audit.services import record
from apps.billing import limits
from apps.core.india import normalise_phone
from apps.core.money import format_inr
from apps.crm import services as crm
from apps.crm.models import ConsentRecord, Lead
from apps.industries.models import LeadSource
from apps.platform_config.services import get as setting
from apps.providers import costs, languages
from apps.providers.adapters import ProviderError
from apps.tenancy.context import company_context, platform_context

from . import cloud
from .models import DefaultTemplate, Template, WaMessage, WhatsAppNumber

log = logging.getLogger(__name__)
RUN_INLINE = False  # tests process webhooks synchronously; the server answers Meta at once and works in a thread


# ------------------------------------------------------------------ numbers (WA-02)
NUMBER_FIELDS = ("e164", "display_name", "phone_number_id", "waba_id", "is_test", "status")


def save_number(number, data, user=None, request=None):
    """Super Admin: add / edit a number of a WhatsApp provider and give it to a company."""
    from apps.providers.models import Provider
    from apps.tenancy.models import Company

    creating = number is None
    number = number or WhatsAppNumber()
    if "provider" in data:
        provider = Provider.objects.filter(key=data["provider"], capabilities__contains=["whatsapp"]).first()
        if not provider:
            raise ValidationError("Choose a WhatsApp provider.")
        number.provider = provider
    for f in NUMBER_FIELDS:
        if f in data:
            value = data[f]
            setattr(number, f, bool(value) if f == "is_test" else str(value or "").strip())
    if "e164" in data:
        number.e164 = normalise_phone(number.e164)
    if "company" in data:
        company = Company.objects.filter(pk=data["company"]).first() if data["company"] else None
        if company != number.company:
            number.employee = None  # a number given to another company leaves the old AI Employee
        number.company = company
    if not number.phone_number_id or not number.waba_id:
        raise ValidationError("Phone number ID and WhatsApp Business Account ID are needed (from Meta).")
    number.full_clean()
    number.save()
    record(
        request,
        "whatsapp_number.create" if creating else "whatsapp_number.update",
        "whatsapp_number",
        number.e164,
        {"company": str(number.company_id or "")},
        user,
    )
    return number


def numbers_for(company):
    with platform_context():
        return list(
            WhatsAppNumber.objects.filter(company=company, status=WhatsAppNumber.ACTIVE).select_related(
                "provider", "employee"
            )
        )


def connect_number(company, number, employee, user=None, request=None):
    """EMP-08: the AI Employee answering this number (one employee per number)."""
    if number.company_id != company.pk:
        raise ValidationError("This number does not belong to your company.")
    if employee is not None and employee.company_id != company.pk:
        raise ValidationError("Unknown AI Employee.")
    with platform_context():
        WhatsAppNumber.objects.filter(pk=number.pk).update(employee=employee)
    number.employee = employee
    record(
        request,
        "whatsapp_number.connect",
        "whatsapp_number",
        number.e164,
        {"employee": str(employee.pk) if employee else None},
        user,
        company=company,
    )
    return number


def number_for(employee):
    with platform_context():
        return (
            WhatsAppNumber.objects.filter(employee=employee, status=WhatsAppNumber.ACTIVE)
            .select_related("provider")
            .first()
        )


def webhook_token(provider):
    from apps.voice.services import _sign

    return _sign(f"whatsapp:{provider.key}")


def webhook_url(provider):
    from django.conf import settings

    return f"{settings.PUBLIC_BASE_URL}/webhooks/whatsapp/{provider.key}/"


# ------------------------------------------------------------------ consent (WA-08, COMP-02, COMP-07)
def _keywords(key):
    return {str(k).strip().lower() for k in setting(key) or [] if str(k).strip()}


def keyword(text):
    t = (text or "").strip().lower().strip(".!")
    if t in _keywords("whatsapp.opt_out_keywords"):
        return "opt_out"
    if t in _keywords("whatsapp.opt_in_keywords"):
        return "opt_in"
    return None


def consent_state(lead):
    """opted_in / opted_out / unknown for WhatsApp (the latest WhatsApp or all-channel record wins)."""
    if lead is None:
        return "unknown"
    last = (
        ConsentRecord.objects.filter(company_id=lead.company_id, lead=lead, channel__in=("whatsapp", "all"))
        .order_by("-created_at")
        .first()
    )
    if last:
        return "opted_out" if last.action == "opt_out" else "opted_in"
    return "opted_out" if lead.consent_status == "opted_out" else "unknown"


def check_can_message(lead):
    """Before any business-initiated message (template)."""
    state = consent_state(lead)
    if state == "opted_out":
        raise ValidationError("This customer opted out of WhatsApp messages.")
    if setting("whatsapp.require_opt_in") and state != "opted_in":
        raise ValidationError("This customer has not opted in to WhatsApp messages yet.")


# ------------------------------------------------------------------ the customer service window
def window_open(company, customer, now=None):
    hours = setting("whatsapp.session_window_hours")
    since = (now or timezone.now()) - timedelta(hours=hours)
    return WaMessage.objects.filter(company=company, customer=customer, direction="in", created_at__gte=since).exists()


def window_closes_at(company, customer):
    last = (
        WaMessage.objects.filter(company=company, customer=customer, direction="in")
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return last + timedelta(hours=setting("whatsapp.session_window_hours")) if last else None


# ------------------------------------------------------------------ sending
def _number_of(conv):
    pk = (conv.state or {}).get("wa_number")
    with platform_context():
        number = WhatsAppNumber.objects.filter(pk=pk).select_related("provider").first() if pk else None
    return number or number_for(conv.employee)


def _log_out(number, company, customer, kind, conversation=None, message=None, lead=None, template=None):
    return WaMessage.objects.create(
        company=company,
        number=number,
        conversation=conversation,
        message=message,
        lead=lead,
        direction="out",
        customer=customer,
        kind=kind,
        template=template,
    )


def _deliver(row, send):
    """Run the provider call and keep the result on the log row."""
    try:
        row.wamid = send()
        row.status, row.status_at = WaMessage.SENT, timezone.now()
    except ProviderError as exc:
        row.status, row.error, row.status_at = WaMessage.FAILED, str(exc)[:500], timezone.now()
    row.save(update_fields=["wamid", "status", "error", "status_at", "updated_at"])
    return row


def send_text(conv, text, message=None):
    """A free-form message inside the customer service window."""
    customer = conv.customer.get("phone", "")
    if not window_open(conv.company, customer):
        raise ValidationError("The 24-hour reply window is closed: send an approved template instead.")
    number = _number_of(conv)
    row = _log_out(number, conv.company, customer, "text", conv, message, conv.lead)
    return _deliver(row, lambda: cloud.for_provider(number.provider).send_text(number, customer, text))


def deliver(conv, msg):
    """Inbox hook: a team reply, a notice or the no-agent message goes to the customer on WhatsApp."""
    if msg.role == "system":
        key = (msg.meta or {}).get("notice")
        if key not in ("chat_waiting", "chat_joined", "chat_ai_back"):
            return None
        lang = conv.language or conv.employee.primary_language
        text = languages.text(lang, key).replace("{name}", (msg.meta or {}).get("name", ""))
        if not text or not window_open(conv.company, conv.customer.get("phone", "")):
            return None
        return send_text(conv, text, msg)
    return send_text(conv, msg.content, msg)


def _media_bytes(media):
    from apps.core.storage import private_storage

    with private_storage.open(media.file_key, "rb") as fh:
        return fh.read()


MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def _mime(name):
    m = re.search(r"\.[a-z0-9]+$", (name or "").lower())
    return MIME.get(m.group(0) if m else "", "application/octet-stream")


def upload(number, media):
    adapter = cloud.for_provider(number.provider)
    return adapter.upload_media(number, _media_bytes(media), _mime(media.file_name), media.file_name)


LATLNG = re.compile(r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$")


def send_item(conv, item, note=""):
    """WA-04 / TOOL-09 inside the window: photos (up to the setting), the brochure and the location of an item."""
    from apps.catalog import services as catalog

    customer = conv.customer.get("phone", "")
    if not window_open(conv.company, customer):
        raise ValidationError("The 24-hour reply window is closed: send an approved template instead.")
    number = _number_of(conv)
    adapter = cloud.for_provider(number.provider)
    sent = []
    photos = list(item.media.filter(kind="photo")[: setting("whatsapp.max_item_photos")])
    for i, media in enumerate(photos):
        row = _log_out(number, conv.company, customer, "image", conv, None, conv.lead)
        caption = (note or item.title) if i == 0 else ""
        _deliver(row, lambda m=media, c=caption: adapter.send_media(number, customer, "image", upload(number, m), c))
        sent.append({"photo": media.file_name, "status": row.status})
    brochure = item.media.filter(kind="brochure").first()
    if brochure:
        row = _log_out(number, conv.company, customer, "document", conv, None, conv.lead)
        _deliver(
            row,
            lambda: adapter.send_media(
                number, customer, "document", upload(number, brochure), item.title, brochure.file_name
            ),
        )
        sent.append({"brochure": brochure.file_name, "status": row.status})
    for d in catalog.fields(conv.company, item.catalog_type):
        value = (item.attributes or {}).get(d.key)
        if d.type == "location" and value:
            row = _log_out(number, conv.company, customer, "location", conv, None, conv.lead)
            match = LATLNG.match(str(value))
            if match:
                lat, lng = float(match.group(1)), float(match.group(2))
                _deliver(row, lambda la=lat, ln=lng: adapter.send_location(number, customer, la, ln, item.title))
            else:  # an address: sent as text so the customer can open it in their maps app
                _deliver(row, lambda v=value: adapter.send_text(number, customer, f"{item.title}: {v}"))
            sent.append({"location": str(value), "status": row.status})
            break
    if not sent:
        raise ValidationError("This item has no photos, brochure or location to send.")
    return sent


# ------------------------------------------------------------------ templates (WA-03, WA-04)
NAME = re.compile(r"^[a-z0-9_]{1,60}$")
VAR = re.compile(r"\{\{(\d+)\}\}")
TEMPLATE_FIELDS = (
    "name",
    "language",
    "meta_language",
    "category",
    "purpose",
    "header_type",
    "header_text",
    "body",
    "footer",
    "buttons",
    "variables",
)


def _clean_template(template):
    from apps.whatsapp.models import CATEGORIES, HEADERS, PURPOSES, VARIABLES

    if not NAME.match(template.name or ""):
        raise ValidationError("Template name: lower-case letters, numbers and underscores only (Meta's rule).")
    if template.category not in dict(CATEGORIES) or template.purpose not in dict(PURPOSES):
        raise ValidationError("Choose the category and purpose.")
    if template.header_type not in dict(HEADERS):
        raise ValidationError("Unknown header type.")
    if template.language not in languages.codes():
        raise ValidationError("Choose one of the platform languages.")
    template.meta_language = template.meta_language or template.language
    if not (template.body or "").strip():
        raise ValidationError("The message text is required.")
    used = sorted({int(n) for n in VAR.findall(template.body)})
    if used and used != list(range(1, len(used) + 1)):
        raise ValidationError("Variables must be numbered {{1}}, {{2}} … without gaps.")
    known = {k for k, _ in VARIABLES}
    variables = [str(v) for v in (template.variables or [])][: len(used)]
    if len(variables) < len(used) or any(v not in known for v in variables):
        raise ValidationError("Choose what fills each variable {{1}}, {{2}} ….")
    template.variables = variables
    if not isinstance(template.buttons, list):
        raise ValidationError("Buttons must be a list.")


def save_template(company, template, data, user=None, request=None):
    """Create or edit a draft (or a rejected template before submitting again)."""
    creating = template is None
    if template is not None and template.status not in (Template.DRAFT, Template.REJECTED):
        raise ValidationError("Approved or submitted templates cannot be edited: copy it under a new name.")
    template = template or Template(company=company)
    if "number" in data:
        number = next((n for n in numbers_for(company) if str(n.pk) == str(data["number"])), None)
        if not number:
            raise ValidationError("Choose one of your WhatsApp numbers.")
        template.number = number
    for f in TEMPLATE_FIELDS:
        if f in data:
            value = data[f]
            setattr(template, f, value if f in ("buttons", "variables") else str(value or "").strip())
    if not template.number_id:
        raise ValidationError("Choose one of your WhatsApp numbers.")
    _clean_template(template)
    if template.status == Template.REJECTED:
        template.status, template.rejected_reason = Template.DRAFT, ""
    template.save()
    record(
        request, "whatsapp_template.save", "whatsapp_template", template.name, {"new": creating}, user, company=company
    )
    return template


def copy_default(company, default, number, language, user=None, request=None):
    """Start a company template from the Super Admin library."""
    texts = (default.texts or {}).get(language) or {}
    if not texts.get("body"):
        raise ValidationError("This library template has no text in that language.")
    return save_template(
        company,
        None,
        {
            "number": number.pk,
            "name": default.name,
            "language": language,
            "category": default.category,
            "purpose": default.purpose,
            "header_type": default.header_type,
            "header_text": texts.get("header", ""),
            "body": texts["body"],
            "footer": texts.get("footer", ""),
            "buttons": default.buttons,
            "variables": default.variables,
        },
        user,
        request,
    )


def submit_template(template, sample=None, user=None, request=None):
    """Send to Meta for review. sample: (bytes, mime) for an image / PDF header."""
    if template.status not in (Template.DRAFT, Template.REJECTED):
        raise ValidationError("Only drafts can be submitted.")
    adapter = cloud.for_provider(template.number.provider)
    try:
        handle = adapter.upload_example(*sample) if sample else ""
        if template.header_type in ("image", "document") and not handle:
            raise ValidationError("Add a sample image / PDF for the header.")
        template.provider_template_id, status = adapter.create_template(template, handle)
    except ProviderError as exc:
        raise ValidationError(f"Meta did not accept the template: {exc}") from None
    template.status = status if status in dict(Template.STATUSES) else Template.PENDING
    template.synced_at = timezone.now()
    template.save(update_fields=["provider_template_id", "status", "synced_at", "updated_at"])
    record(
        request, "whatsapp_template.submit", "whatsapp_template", template.name, None, user, company=template.company
    )
    return template


def delete_template(template, user=None, request=None):
    """Drafts are removed here; submitted templates are deleted at Meta too."""
    if template.status != Template.DRAFT and template.provider_template_id:
        try:
            cloud.for_provider(template.number.provider).delete_template(template)
        except ProviderError as exc:
            raise ValidationError(f"Meta did not delete the template: {exc}") from None
    record(
        request, "whatsapp_template.delete", "whatsapp_template", template.name, None, user, company=template.company
    )
    template.delete()


def check_default(name, texts, variables):
    """Super Admin library row: Meta's name rule, a body per language, one source per variable."""
    from apps.whatsapp.models import VARIABLES

    if not NAME.match(name or ""):
        raise ValidationError("Name: lower-case letters, numbers and underscores only (Meta's rule).")
    if (
        not isinstance(texts, dict)
        or not texts
        or not all(isinstance(t, dict) and t.get("body") for t in texts.values())
    ):
        raise ValidationError('Texts: {"en": {"body": "…"}, …} with a body for each language.')
    known = {k for k, _ in VARIABLES}
    for code, t in texts.items():
        used = sorted({int(n) for n in VAR.findall(t["body"])})
        if used != list(range(1, len(used) + 1)) or len(used) > len(variables or []):
            raise ValidationError(f"{code}: variables must be {{{{1}}}} … and each needs a source.")
    if any(v not in known for v in variables or []):
        raise ValidationError("Unknown variable source.")


def sync_templates(company):
    """WA-03: approval status from Meta for every template of the company's accounts. → changed count"""
    changed = 0
    by_waba = {}
    for t in Template.objects.filter(company=company).exclude(status=Template.DRAFT).select_related("number"):
        by_waba.setdefault((t.number.waba_id, t.number.provider_id), []).append(t)
    for (waba, _), rows in by_waba.items():
        try:
            remote = cloud.for_provider(rows[0].number.provider).list_templates(waba)
        except ProviderError as exc:
            raise ValidationError(f"Could not reach Meta: {exc}") from None
        index = {(r.get("name"), r.get("language")): r for r in remote}
        for t in rows:
            r = index.get((t.name, t.meta_language))
            status = str(r.get("status", "")).lower() if r else ""
            if status in dict(Template.STATUSES) and (status != t.status or r.get("id") != t.provider_template_id):
                t.status, t.provider_template_id = status, r.get("id") or t.provider_template_id
                t.rejected_reason = str(r.get("rejected_reason") or "")[:500] if status == Template.REJECTED else ""
                changed += 1
            t.synced_at = timezone.now()
            t.save(update_fields=["status", "provider_template_id", "rejected_reason", "synced_at", "updated_at"])
    return changed


def _value(source, ctx):
    lead, company, employee = ctx.get("lead"), ctx.get("company"), ctx.get("employee")
    appointment, item = ctx.get("appointment"), ctx.get("item")
    if source == "lead.name":
        return (lead.name if lead else "") or "Customer"
    if source == "company.name":
        return company.name
    if source == "employee.name":
        return employee.name if employee else ""
    if source.startswith("appointment.") and appointment:
        from apps.scheduling.services import tz_for

        if source == "appointment.when":
            return f"{appointment.starts_at.astimezone(tz_for(appointment.resource)):%a %d %b %Y, %H:%M}"
        if source == "appointment.number":
            return appointment.reference
        return appointment.appointment_type.name
    if source == "item.title" and item:
        return item.title
    if source == "item.price" and item:
        return format_inr(item.price_paise) if item.price_paise is not None else ""
    if source == "text":
        return ctx.get("text") or ""
    return ""


def params_for(template, ctx):
    values = [str(_value(s, ctx)).strip() for s in template.variables or []]
    missing = [i + 1 for i, v in enumerate(values) if not v]
    if missing:
        names = ", ".join("{{" + str(n) + "}}" for n in missing)
        raise ValidationError(f"No value for {names} of this template.")
    return values


def preview(template, params):
    return VAR.sub(
        lambda m: params[int(m.group(1)) - 1] if int(m.group(1)) <= len(params) else m.group(0), template.body
    )


def find_template(company, purpose, language):
    qs = Template.objects.filter(company=company, purpose=purpose, status=Template.APPROVED).select_related("number")
    return qs.filter(language=language).first() or qs.first()


def send_template(template, lead, ctx=None, user=None, conversation=None, request=None):
    """WA-04: an approved template to a lead (outside or inside the window)."""
    if template.status != Template.APPROVED:
        raise ValidationError("Only templates approved by Meta can be sent.")
    if not lead or not lead.phone:
        raise ValidationError("The customer has no mobile number.")
    check_can_message(lead)
    ctx = {"lead": lead, "company": template.company, **(ctx or {})}
    params = params_for(template, ctx)
    number = template.number
    adapter = cloud.for_provider(number.provider)
    media_id = ""
    if template.header_type in ("image", "document"):
        kind = "photo" if template.header_type == "image" else "brochure"
        item = ctx.get("item")
        media = item.media.filter(kind=kind).first() if item else None
        if not media:
            raise ValidationError(f"Choose a property / product with a {kind} for this template's header.")
        try:
            media_id = upload(number, media)
        except ProviderError as exc:
            raise ValidationError(f"The {kind} could not be uploaded: {exc}") from None
    text = preview(template, params)
    msg = None
    if conversation is not None:
        msg = Message.objects.create(
            company=template.company,
            conversation=conversation,
            role="human" if user else "ai",
            content=text,
            language=template.language,
            meta={
                "template": template.name,
                **({"name": inbox.first_name(user), "user": str(user.pk)} if user else {}),
            },
        )
    row = _log_out(number, template.company, lead.phone, "template", conversation, msg, lead, template)
    _deliver(row, lambda: adapter.send_template(number, lead.phone, template, params, media_id))
    if row.status == WaMessage.FAILED:
        raise ValidationError(f"WhatsApp did not accept the message: {row.error}")
    crm.log(lead, "whatsapp", f"WhatsApp template sent: {template.name}", user, actor_type="user" if user else "ai")
    record(
        request, "whatsapp.send_template", "lead", str(lead.pk), {"template": template.name}, user, company=lead.company
    )
    return row


def send_alert(company, phone, text):
    """NOTI-03: an alert to a team member's own WhatsApp (the company's approved "Team alert" template). Team members
    are not customers: no consent record or CRM entry, only the message log."""
    template = find_template(company, "team_alert", company.default_language or setting("locale.default_language"))
    if not template:
        raise ValidationError('No approved WhatsApp "Alert to your team" template (Settings → WhatsApp).')
    params = params_for(template, {"company": company, "text": text})
    number = template.number
    row = _log_out(number, company, phone, "template", template=template)
    _deliver(row, lambda: cloud.for_provider(number.provider).send_template(number, phone, template, params, ""))
    if row.status == WaMessage.FAILED:
        raise ValidationError(f"WhatsApp did not accept the alert: {row.error}")
    return row


# ------------------------------------------------------------------ inbound (webhook)
def handle_webhook(provider, payload):
    """Meta's webhook body → messages and statuses. Each message is processed once (WebhookEvent)."""
    from apps.voice.models import WebhookEvent

    jobs = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            phone_id = (value.get("metadata") or {}).get("phone_number_id", "")
            contacts = {c.get("wa_id"): c for c in value.get("contacts") or []}
            for msg in value.get("messages") or []:
                try:
                    with transaction.atomic():
                        WebhookEvent.objects.create(
                            provider_key=provider.key, event_key=f"wa:{msg.get('id')}", payload={"phone_id": phone_id}
                        )
                except IntegrityError:  # nosec B112 — already received (Meta retries the same message)
                    continue
                jobs.append((phone_id, msg, contacts.get(msg.get("from")) or {}))
            for st in value.get("statuses") or []:
                status_update(phone_id, st)
    for job in jobs:
        if RUN_INLINE:
            receive(*job)
        else:  # ponytail: a thread per message; move to a worker queue if WhatsApp volume grows
            threading.Thread(target=_receive_thread, args=job, daemon=True).start()


def _receive_thread(*job):
    try:
        receive(*job)
    except Exception:  # noqa: BLE001 — never lose the thread silently
        log.exception("whatsapp message failed")
    finally:
        close_old_connections()


def _number(phone_id):
    with platform_context():
        return (
            WhatsAppNumber.objects.filter(phone_number_id=phone_id, status=WhatsAppNumber.ACTIVE)
            .select_related("provider", "company", "employee")
            .first()
        )


def _text_of(number, msg, language):
    """→ (text for the AI and the transcript, kind, extra meta)."""
    kind = msg.get("type", "text")
    if kind == "text":
        return (msg.get("text") or {}).get("body", ""), kind, {}
    if kind == "button":
        return (msg.get("button") or {}).get("text", ""), kind, {}
    if kind == "interactive":
        it = msg.get("interactive") or {}
        reply = it.get("button_reply") or it.get("list_reply") or {}
        return reply.get("title", ""), kind, {}
    if kind == "location":
        loc = msg.get("location") or {}
        where = loc.get("name") or loc.get("address") or f"{loc.get('latitude')},{loc.get('longitude')}"
        return f"[Location] {where}", kind, {"location": loc}
    if kind in ("audio", "voice"):  # WA-09 voice note → transcript
        from apps.providers.transcribe import transcribe

        media = msg.get(kind) or {}
        try:
            audio, mime = cloud.for_provider(number.provider).download_media(media.get("id", ""))
            text, provider_key = transcribe(audio, mime.split(";")[0], language)
            return text, "voice_note", {"voice_note": True, "stt": provider_key}
        except ProviderError as exc:
            log.warning("voice note not transcribed: %s", exc)
            return "", "voice_note", {"voice_note": True, "stt_error": str(exc)[:200]}
    if kind in ("image", "document", "video", "sticker"):
        media = msg.get(kind) or {}
        label = media.get("caption") or media.get("filename") or kind
        return f"[{kind.title()}] {label}", kind, {"media_id": media.get("id", "")}
    return "", kind, {}


def _conversation(number, customer, name):
    """The open WhatsApp conversation of this customer with the number's AI Employee, or a new one."""
    employee = number.employee
    conv = (
        Conversation.objects.filter(
            company=number.company, employee=employee, channel="whatsapp", status=Conversation.ACTIVE
        )
        .filter(customer__phone=customer)
        .select_related("employee", "lead", "company", "assigned_user")
        .first()
    )
    if conv:
        return conv, False
    month = timezone.localdate().replace(day=1)
    used = Conversation.objects.filter(
        company=number.company, channel="whatsapp", is_test=False, started_at__date__gte=month
    ).count()
    cap = limits.hard_cap(number.company, "whatsapp_conversations")
    over = cap is not None and used >= cap
    from apps.billing import access

    if employee.status == employee.ACTIVE and not over and not access.blocked(number.company, "whatsapp"):
        conv = runtime.start(employee, "whatsapp", {"phone": customer, "name": name})
    else:  # AI paused or plan limit reached: the chat waits for a person in the inbox
        lead = Lead.objects.filter(company=number.company, phone=customer, deleted_at__isnull=True).first()
        conv = Conversation.objects.create(
            company=number.company,
            employee=employee,
            employee_version=employee.config_version,
            lead=lead,
            channel="whatsapp",
            customer={"phone": customer, "name": name},
            language=employee.primary_language,
            handled_by=Conversation.WAITING,
            state={"reason": "plan_limit" if over else "employee_inactive"},
        )
    conv.state = {**(conv.state or {}), "wa_number": str(number.pk)}
    conv.save(update_fields=["state", "updated_at"])
    return conv, True


def _ensure_lead(conv, customer, name):
    if conv.lead_id:
        return conv.lead
    lead = Lead.objects.filter(company=conv.company, phone=customer, deleted_at__isnull=True).first()
    if lead is None:
        data = {"name": name, "phone": customer, "preferred_language": conv.language}
        if LeadSource.objects.filter(key="whatsapp", is_active=True).exists():
            data["source"] = "whatsapp"
        try:
            lead = crm.create_lead(conv.company, data, created_via="ai")
        except crm.DuplicateLead as dup:
            lead = dup.lead
    conv.lead = lead
    conv.save(update_fields=["lead", "updated_at"])
    return lead


def receive(phone_id, msg, contact):
    number = _number(phone_id)
    if not number or not number.company_id or not number.employee_id:
        log.warning("WhatsApp message for an unconnected number %s ignored", phone_id)
        return
    customer = normalise_phone("+" + str(msg.get("from", "")))
    name = ((contact.get("profile") or {}).get("name") or "")[:150]
    with company_context(number.company_id):
        conv, new = _conversation(number, customer, name)
        language = conv.language or conv.employee.primary_language
        text, kind, extra = _text_of(number, msg, language)
        row = WaMessage.objects.create(
            company=conv.company,
            number=number,
            conversation=conv,
            lead=conv.lead,
            direction="in",
            wamid=str(msg.get("id", "")),
            customer=customer,
            kind=kind,
            status=WaMessage.RECEIVED,
            status_at=timezone.now(),
        )
        if setting("whatsapp.read_receipts"):
            try:
                cloud.for_provider(number.provider).mark_read(number, row.wamid)
            except ProviderError:
                pass
        action = keyword(text)
        lead = conv.lead
        if action or (setting("whatsapp.inbound_is_opt_in") and consent_state(lead) == "unknown"):
            lead = _ensure_lead(conv, customer, name)
        if action:
            crm.record_consent(
                lead, "whatsapp", action, "whatsapp_keyword", evidence={"text": text, "wamid": row.wamid}
            )
            stored = inbox.customer_message(conv, text)
            row.message, row.lead = stored, lead
            row.save(update_fields=["message", "lead", "updated_at"])
            reply = languages.text(language, "wa_opted_out" if action == "opt_out" else "wa_opted_in")
            if reply:
                send_text(conv, runtime._render(reply, conv.employee))
            return
        if lead and consent_state(lead) == "unknown" and setting("whatsapp.inbound_is_opt_in"):
            crm.record_consent(lead, "whatsapp", "opt_in", "customer_message", evidence={"wamid": row.wamid})
        if not text:  # a sticker, an unreadable voice note …: stored, the team sees it in the inbox
            text = "[Voice note — could not be transcribed]" if extra.get("voice_note") else f"[{kind}]"
            stored = inbox.customer_message(conv, text)
            stored.meta = extra
            stored.save(update_fields=["meta", "updated_at"])
            row.message = stored
            row.save(update_fields=["message", "updated_at"])
            return
        if new and conv.handled_by == Conversation.AI:  # COMP-01: the AI disclosure is sent first
            opening = conv.messages.filter(meta__opening=True).first()
            if opening:
                send_text(conv, opening.content, opening)
        if conv.handled_by != Conversation.AI:
            stored = inbox.customer_message(conv, text)
        else:
            answer = runtime.reply(conv, text)
            stored = conv.messages.filter(role="customer").order_by("-created_at").first()
            send_text(conv, answer.content, answer)
            inbox.after_ai_reply(conv)
        if extra:
            stored.meta = {**(stored.meta or {}), **extra}
            stored.save(update_fields=["meta", "updated_at"])
        row.message = stored
        row.save(update_fields=["message", "updated_at"])


def status_update(phone_id, st):
    """WA-10: sent / delivered / read / failed and the pricing category; usage is metered once per message."""
    number = _number(phone_id)
    if not number or not number.company_id:
        return
    with company_context(number.company_id):
        row = WaMessage.objects.filter(company=number.company, wamid=str(st.get("id", ""))).first()
        if row is None:
            return
        new = str(st.get("status", "")).lower()
        if new == WaMessage.FAILED:
            err = (st.get("errors") or [{}])[0]
            row.status, row.error = new, str(err.get("message") or err.get("title") or "Failed")[:500]
        elif new in WaMessage.ORDER and WaMessage.ORDER[new] > WaMessage.ORDER.get(row.status, -1):
            row.status = new
        row.status_at = timezone.now()
        pricing = st.get("pricing") or {}
        first_pricing = pricing and not row.category
        if pricing:
            row.category = str(pricing.get("category", ""))[:20]
            row.billable = bool(pricing.get("billable"))
        row.save(update_fields=["status", "error", "status_at", "category", "billable", "updated_at"])
        if first_pricing:
            conv = row.conversation
            UsageEvent.objects.create(
                company=number.company,
                employee=conv.employee if conv else number.employee,
                conversation=conv,
                meter="whatsapp_messages",
                quantity=1,
                unit="messages",
                task=row.category,
                provider_key=number.provider.key,
                model="billable" if row.billable else "free",
                provider_cost_paise=(
                    costs.paise(costs.config_price(number.provider, f"cost_{row.category.lower()}"))
                    if row.billable
                    else 0
                ),
            )


# ------------------------------------------------------------------ follow-up after a call (WA-04, EMP-08)
def after_conversation(conv):
    """A call that ended with a follow-up need → the approved lead follow-up template (rule per AI Employee)."""
    rules = conv.employee.rules or {}
    if conv.channel != "voice" or conv.is_test or not rules.get("whatsapp_after_call") or not conv.lead_id:
        return None
    template = find_template(conv.company, "lead_follow_up", conv.language or conv.employee.primary_language)
    if not template:
        crm.log(conv.lead, "whatsapp", "No approved WhatsApp follow-up template to send after the call", None, "system")
        return None
    try:
        return send_template(template, conv.lead, {"employee": conv.employee})
    except ValidationError as exc:
        crm.log(conv.lead, "whatsapp", f"WhatsApp follow-up not sent: {exc.messages[0]}", None, "system")
        return None


def library():
    return DefaultTemplate.objects.filter(is_active=True)
