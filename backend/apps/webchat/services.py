"""Website chat widget (CHAT-01 … CHAT-07): settings, the embed snippet, and the visitor's conversation.

A visitor's chat is an ordinary AI conversation (channel "web_chat") run by the shared engine; the shared inbox
(apps.agents.inbox) decides whether the AI or a person answers. The browser holds a signed token for its own
conversation only — never an id it could change.
"""

import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.agents import inbox, runtime
from apps.agents.models import Conversation, Message
from apps.audit.services import record
from apps.crm import services as crm
from apps.industries.models import LeadSource
from apps.platform_config.services import get as setting
from apps.providers import languages
from apps.providers.models import CHAT_TEXT_KEYS
from apps.tenancy.context import platform_context

from .models import ChatWidget

SALT = "webchat.v1"
DOMAIN = re.compile(r"^(localhost|[a-z0-9-]+(\.[a-z0-9-]+)+|\d{1,3}(\.\d{1,3}){3})(:\d{1,5})?$")


# ------------------------------------------------------------------ settings (company panel / API)
def widget_for(employee):
    widget = ChatWidget.objects.filter(employee=employee).first()
    return widget or ChatWidget.objects.create(company=employee.company, employee=employee)


def clean_domain(value):
    """'https://www.Example.com/contact' → 'www.example.com'; a port is kept (local test sites)."""
    value = str(value or "").strip().lower()
    if not value:
        return ""
    netloc = urlsplit(value if "//" in value else "//" + value).netloc
    netloc = netloc.removeprefix("*.")
    if not DOMAIN.match(netloc):
        raise ValidationError(f"“{value}” is not a website address (e.g. example.com).")
    return netloc


COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
FIELDS = ("is_enabled", "title", "subtitle", "avatar", "color", "position", "language")


def save_widget(widget, data, user=None, request=None):
    changes = {}
    for f in FIELDS:
        if f in data:
            value = data[f]
            value = bool(value) if f == "is_enabled" else str(value or "").strip()
            if getattr(widget, f) != value:
                changes[f] = value
                setattr(widget, f, value)
    if widget.color and not COLOR.match(widget.color):
        raise ValidationError("Colour must look like #1A2B3C.")
    if widget.position not in dict(ChatWidget.POSITIONS):
        raise ValidationError("Choose where the chat button sits.")
    codes = widget.employee.languages or [widget.employee.primary_language]
    if widget.language and widget.language not in codes:
        raise ValidationError("The opening language must be one the AI Employee speaks.")
    for f in ("greetings", "launcher_text"):
        if f in data:
            texts = {c: str(v).strip() for c, v in (data[f] or {}).items() if c in codes and str(v or "").strip()}
            if texts != getattr(widget, f):
                changes[f] = sorted(texts)
                setattr(widget, f, texts)
    if "allowed_domains" in data:
        raw = data["allowed_domains"]
        raw = raw.splitlines() if isinstance(raw, str) else raw or []
        domains = sorted({d for d in (clean_domain(x) for x in raw) if d})
        if domains != widget.allowed_domains:
            changes["allowed_domains"] = domains
            widget.allowed_domains = domains
    if "actions" in data:
        actions = {k: bool((data["actions"] or {}).get(k)) for k, _ in ChatWidget.ACTIONS}
        if actions != widget.actions:
            changes["actions"] = actions
            widget.actions = actions
    if "regenerate_key" in data and data["regenerate_key"]:
        from .models import new_key

        widget.key = new_key()
        changes["key"] = "regenerated"
    widget.save()
    if changes:
        record(request, "widget.update", "chat_widget", str(widget.pk), changes, user, company=widget.company)
    return widget


def script_url():
    return settings.PUBLIC_BASE_URL + settings.STATIC_URL + "webchat/widget.js"


def snippet(widget):
    """CHAT-01: what the company pastes into its website (before </body>)."""
    return f'<script src="{script_url()}" data-key="{widget.key}" async></script>'


# ------------------------------------------------------------------ public side: key, origin, appearance
def resolve(key):
    """The widget behind a public key, if it may chat now (company context is set by the caller)."""
    with platform_context():
        widget = (
            ChatWidget.all_companies.select_related("employee", "company", "employee__company")
            .filter(key=str(key or "")[:40])
            .first()
        )
    if not widget or not widget.is_enabled or widget.company.status not in ("trial", "active"):
        return None
    if widget.company.deleted_at or widget.employee.status != widget.employee.ACTIVE:
        return None
    return widget


def _own_hosts():
    return {urlsplit(settings.PUBLIC_BASE_URL).netloc.lower(), *[h.lower() for h in settings.ALLOWED_HOSTS if h]}


def origin_allowed(widget, origin):
    """CHAT-05: the page showing the widget must be one of the company's websites (or our own preview page)."""
    if not origin:
        return True  # not a browser page (the app, server tests); rate limits still apply
    host = urlsplit(origin).netloc.lower()
    if host in _own_hosts():
        return True
    domains = widget.allowed_domains or []
    if not domains:
        return not setting("chat.require_allowed_domains")
    for d in domains:
        if host == d or (":" not in d and host.split(":")[0].endswith("." + d)) or host.split(":")[0] == d:
            return True
    return False


def _texts(code):
    return {k.removeprefix("chat_"): languages.text(code, k) for k in CHAT_TEXT_KEYS}


def public_config(widget):
    """CHAT-02: everything the widget draws, in every language the AI Employee speaks."""
    employee = widget.employee
    codes = employee.languages or [employee.primary_language]
    names = languages.names()
    texts = {}
    for code in codes:
        t = _texts(code)
        t["launcher"] = (widget.launcher_text or {}).get(code) or t["launcher"]
        texts[code] = t
    return {
        "title": widget.title or employee.name,
        "subtitle": widget.subtitle or widget.company.name,
        "avatar": _absolute(widget.avatar or employee.avatar),
        "color": widget.color or setting("general.color_primary"),
        "position": widget.position,
        "language": widget.language or employee.primary_language,
        "languages": [{"code": c, "name": names.get(c, c)} for c in codes],
        "texts": texts,
        "actions": [k for k, _ in ChatWidget.ACTIONS if widget.action_on(k)],
        "poll_seconds": setting("chat.poll_seconds"),
        "min_seconds": setting("chat.bot_min_seconds"),
        "powered_by": setting("general.widget_powered_by"),
    }


def _absolute(url):
    if url and url.startswith("/"):
        return settings.PUBLIC_BASE_URL + url
    return url or ""


# ------------------------------------------------------------------ public side: the visitor's conversation
def token_for(conv):
    return signing.dumps(str(conv.pk), salt=SALT, compress=True)


def conversation_for(widget, token):
    try:
        pk = signing.loads(str(token or ""), salt=SALT)
    except signing.BadSignature:
        return None
    return (
        Conversation.objects.select_related("employee", "lead", "assigned_user", "company")
        .filter(pk=pk, employee=widget.employee, channel="web_chat")
        .first()
    )


def start(widget, language="", page=""):
    employee = widget.employee
    codes = employee.languages or [employee.primary_language]
    language = language if language in codes else (widget.language or employee.primary_language)
    conv = runtime.start(employee, "web_chat", {"language": language})
    conv.customer = {"page": str(page or "")[:300]}
    conv.save(update_fields=["customer", "updated_at"])
    own = (widget.greetings or {}).get(language)
    if own:  # the widget's own greeting replaces the employee's; the AI disclosure always stays first
        opening = conv.messages.get(meta__opening=True)
        opening.content = " ".join(
            t for t in (runtime.disclosure(employee, language), runtime._render(own, employee)) if t
        )
        opening.save(update_fields=["content", "updated_at"])
    return conv


def out(msg):
    row = {"id": str(msg.id), "role": msg.role, "text": msg.content, "at": msg.created_at.isoformat()}
    if msg.role == "human":
        row["name"] = (msg.meta or {}).get("name", "")
    if msg.role == "system":
        row.update(text="", notice=(msg.meta or {}).get("notice", ""), name=(msg.meta or {}).get("name", ""))
    if (msg.meta or {}).get("ask_contact"):
        row["ask_contact"] = True
    return row


VISIBLE = ("customer", "ai", "human", "system")


def messages_after(conv, after=""):
    qs = conv.messages.filter(role__in=VISIBLE).order_by("created_at")
    if after:
        last = conv.messages.filter(pk=after).values_list("created_at", flat=True).first() if _uuid(after) else None
        if last:
            qs = qs.filter(created_at__gt=last)
    return [out(m) for m in qs]


def _uuid(value):
    return bool(re.fullmatch(r"[0-9a-f-]{36}", str(value)))


def state(conv):
    """What the widget shows above the messages: who answers now."""
    from apps.voice import handoff

    if conv.handled_by == Conversation.WAITING:
        handoff.expire_ringing(conversation=conv)
        conv.refresh_from_db(fields=["handled_by", "assigned_user", "status"])
    return {
        "status": conv.status,
        "handled_by": conv.handled_by,
        "agent": inbox.first_name(conv.assigned_user) if conv.handled_by == Conversation.HUMAN else "",
    }


def send(conv, text):
    """One visitor message → the AI's answer (or nothing yet when a person handles the chat)."""
    first = not conv.messages.filter(role="customer").exists()
    wait = setting("chat.bot_min_seconds")
    if first and wait and (timezone.now() - conv.started_at).total_seconds() < wait:
        raise ValidationError("Please wait a moment before sending.")
    if conv.handled_by != Conversation.AI:
        inbox.customer_message(conv, text)
        return
    runtime.reply(conv, text)
    inbox.after_ai_reply(conv)


def ask_for_person(conv):
    inbox.request_human(conv, "customer_request", "Asked in the website chat")


KINDS = ("enquiry", "callback")


def contact(widget, conv, kind, data):
    """CHAT-03 / CHAT-04: enquiry or callback form → the CRM lead (source Website Chat), a note and a task."""
    if kind not in KINDS or not widget.action_on(kind):
        raise ValidationError("This form is not available.")
    name = str(data.get("name") or "").strip()[:150]
    phone = str(data.get("phone") or "").strip()[:20]
    email = str(data.get("email") or "").strip()[:254]
    message = str(data.get("message") or "").strip()[:1000]
    if not name or not phone:
        raise ValidationError("Please give your name and mobile number.")
    lead = conv.lead if conv and conv.lead_id else None
    company = widget.company
    if lead is None:
        payload = {"name": name, "phone": phone, "email": email, "preferred_language": conv.language if conv else ""}
        if LeadSource.objects.filter(key="website_chat", is_active=True).exists():  # CHAT-04 source Website Chat
            payload["source"] = "website_chat"
        try:
            lead = crm.create_lead(company, payload, created_via="website")
        except crm.DuplicateLead as dup:
            lead = dup.lead
        lead.assigned_ai_employee_id = lead.assigned_ai_employee_id or widget.employee_id
        lead.save(update_fields=["assigned_ai_employee_id", "updated_at"])
    else:
        crm.update_lead(lead, {k: v for k, v in {"name": name, "email": email}.items() if v and not getattr(lead, k)})
    title = dict(ChatWidget.ACTIONS)[kind]
    crm.add_note(lead, f"{title} (website chat): {message or '—'}")
    crm.create_task(
        company,
        {
            "title": f"{'Call back' if kind == 'callback' else 'Reply to enquiry'}: {lead.name or lead.reference}",
            "notes": message,
            "due_at": timezone.now(),
            "lead": lead,
            "type": "callback" if kind == "callback" else "follow_up",
        },
    )
    if conv:
        conv.lead = lead
        conv.customer = {**(conv.customer or {}), "name": name, "phone": lead.phone, "email": email}
        conv.save(update_fields=["lead", "customer", "updated_at"])
        Message.objects.create(
            company=company,
            conversation=conv,
            role="system",
            content="chat_thanks",
            meta={"notice": "chat_thanks", "form": kind},
        )
    return lead
