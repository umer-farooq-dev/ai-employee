"""Tool framework (M09: TOOL-01 … TOOL-07, TOOL-13 … TOOL-15, CAT-03, CAL-06, SEC-14).

The model only sees each tool's name, description and JSON schema. The server validates the arguments, takes
company / employee / conversation / lead from the session (never from the model), runs the handler, and records
every call (ToolInvocation). Write tools are idempotent per conversation turn, so a retry never double-books.
"""

import datetime as dt
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from jsonschema import Draft7Validator

from apps.catalog import services as catalog
from apps.catalog.models import CatalogItem
from apps.core.india import parse_indian_date
from apps.core.money import format_inr, parse_inr
from apps.crm import services as crm
from apps.crm.models import Lead
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.industries.models import LeadSource
from apps.platform_config.services import get as setting
from apps.roles_tools.models import Tool
from apps.scheduling import services as calendar
from apps.scheduling.models import Appointment, Resource

from .models import Conversation, ToolInvocation

log = logging.getLogger(__name__)
MAX_RESULTS = 10
CHANNEL_SOURCE = {"voice": "inbound_call", "whatsapp": "whatsapp", "web_chat": "website_chat", "test": "website_chat"}


def company_tz(company):
    from zoneinfo import ZoneInfo

    return ZoneInfo(company.timezone or setting("locale.timezone"))


def today(company):
    return timezone.localdate(timezone=company_tz(company))


class ToolError(Exception):
    """A problem the AI can act on (told back to the model as the tool result)."""


@dataclass
class ToolContext:
    company: object
    employee: object
    conversation: object
    lead: object = None
    turn: int = 0
    notes: dict = field(default_factory=dict)  # facts returned by tools this turn (grounding check)


# ------------------------------------------------------------------ helpers
def _lead_fields(ctx, ai_only=True):
    defs = templates.fields_for(ctx.company, "lead")
    return [d for d in defs if d.is_active and (d.ai_extractable or not ai_only)]


def _json_type(defn):
    if defn.type in ("number",):
        return {"type": "number"}
    if defn.type == "yes_no":
        return {"type": "boolean"}
    if defn.type == "multi_select":
        return {"type": "array", "items": {"type": "string", "enum": [v for v, _ in field_engine.options(defn)]}}
    if defn.type == "single_select":
        return {"type": "string", "enum": [v for v, _ in field_engine.options(defn)]}
    hint = {"currency": "Amount, e.g. 70 lakh or 7000000", "date": "Date, e.g. 2026-11-15 or 'next Sunday'"}
    return {"type": "string", **({"description": hint[defn.type]} if defn.type in hint else {})}


def _fields_schema(defs):
    props = {}
    for d in defs:
        props[d.key] = {**_json_type(d)}
        desc = " — ".join(x for x in (d.label, d.extraction_hint, props[d.key].get("description", "")) if x)
        props[d.key]["description"] = desc
    return {"type": "object", "properties": props, "additionalProperties": False}


def _normalise_fields(ctx, values):
    """AI values checked by the field engine; Indian date words become ISO dates (lakh / crore stay as said)."""
    defs = {d.key: d for d in _lead_fields(ctx, ai_only=False)}
    out = {}
    for key, value in (values or {}).items():
        d = defs.get(key)
        if not d:
            continue
        if d.type in ("date", "datetime") and isinstance(value, str):
            parsed = parse_indian_date(value, today(ctx.company))
            value = parsed.isoformat() if parsed else value
        out[key] = value
    crm.clean_custom(ctx.company, out, partial=True)  # validate; update_lead stores (and converts) the raw values
    return out


def _lead_summary(lead):
    defs = {d.key: d for d in templates.fields_for(lead.company, "lead")}
    return {
        "lead_id": lead.reference,
        "name": lead.name,
        "status": lead.status.label,
        "score": lead.score_label,
        "fields": {defs[k].label: field_engine.display(defs[k], v) for k, v in lead.custom.items() if k in defs and v},
    }


def _need_lead(ctx):
    if not ctx.lead:
        raise ToolError("No lead yet: call create_lead with the customer's name and phone first.")
    return ctx.lead


def _catalog_type(ctx, tool, args):
    key = tool.config.get("catalog_type") or args.get("catalog_type")
    ctype = next((t for t in templates.catalog_types(ctx.company) if t.key == key), None)
    if not ctype:
        raise ToolError(f"Unknown catalogue {key!r}.")
    return ctype


def _item_out(ctype, item, defs, extra=None):
    out = {"item_id": str(item.pk), "title": item.title}
    if item.price_paise is not None:
        out["price"] = format_inr(item.price_paise)
    for d in defs:
        if d.key in item.attributes and (d.show_in_list or d.filterable or (extra and d.key in extra)):
            value = field_engine.display(d, item.attributes[d.key])
            if value:
                out[d.label] = value
    return out


def _appointment_type(ctx, tool, args):
    key = tool.config.get("appointment_type") or args.get("appointment_type")
    t = next((t for t in templates.appointment_types(ctx.company) if t.key == key), None)
    if not t:
        raise ToolError(f"Unknown appointment type {key!r}.")
    return t


def _resources(ctx, appt_type):
    qs = Resource.objects.filter(company=ctx.company, is_active=True)
    allowed = [str(r) for r in ctx.employee.calendar_resources or []]
    if allowed:
        qs = qs.filter(pk__in=allowed)
    return [r for r in qs if not r.appointment_types or appt_type.key in r.appointment_types]


def _parse_start(value, resource):
    try:
        start = dt.datetime.fromisoformat(str(value))
    except ValueError:
        raise ToolError("start must be an ISO date-time from check_availability, e.g. 2026-11-15T11:00") from None
    if timezone.is_naive(start):
        start = start.replace(tzinfo=calendar.tz_for(resource))
    return start


def _lead_appointment(ctx, args):
    lead = _need_lead(ctx)
    qs = Appointment.objects.filter(company=ctx.company, lead=lead, status__in=Appointment.ACTIVE)
    if args.get("appointment_number"):
        number = "".join(ch for ch in str(args["appointment_number"]) if ch.isdigit())
        qs = qs.filter(number=int(number or 0))
    appt = qs.order_by("starts_at").first()
    if not appt:
        raise ToolError("This customer has no upcoming appointment.")
    return appt


def _track(ctx, kind, obj):
    """Records made by a test conversation are removed when the test ends (runtime.end)."""
    if ctx.conversation.is_test and obj is not None:
        ctx.conversation.state.setdefault("created", {}).setdefault(kind, []).append(str(obj.pk))


def _validation(exc):
    return "; ".join(getattr(exc, "messages", [str(exc)]))


# ------------------------------------------------------------------ handlers: CRM (TOOL-02, 03, 06)
def create_lead(ctx, tool, args):
    if ctx.lead:
        return {"already_exists": True, **update_lead(ctx, tool, args)}
    channel = ctx.conversation.channel
    data = {
        "name": args.get("name") or ctx.conversation.customer.get("name", ""),
        "phone": args.get("phone") or ctx.conversation.customer.get("phone", ""),
        "email": args.get("email") or ctx.conversation.customer.get("email", ""),
        "preferred_language": ctx.conversation.language or "",
    }
    source = LeadSource.objects.filter(key=CHANNEL_SOURCE.get(channel, ""), is_active=True).first()
    if source:
        data["source"] = source.key
    try:
        lead = crm.create_lead(ctx.company, data, created_via="ai")
        _track(ctx, "leads", lead)
    except crm.DuplicateLead as dup:
        lead = dup.lead
    except ValidationError as exc:
        raise ToolError(_validation(exc)) from None
    lead.assigned_ai_employee_id = ctx.employee.pk
    lead.save(update_fields=["assigned_ai_employee_id", "updated_at"])
    ctx.lead = lead
    ctx.conversation.lead = lead
    ctx.conversation.save(update_fields=["lead", "updated_at"])
    if args.get("fields"):
        return update_lead(ctx, tool, args)
    return {"created": True, **_lead_summary(lead)}


def update_lead(ctx, tool, args):
    lead = _need_lead(ctx)
    data = {}
    for key in ("name", "email"):
        if args.get(key):
            data[key] = args[key]
    if args.get("status"):
        data["status"] = args["status"]
    if args.get("next_action"):
        data["next_action"] = args["next_action"]
    try:
        if args.get("fields"):
            data["custom"] = _normalise_fields(ctx, args["fields"])
        crm.update_lead(lead, data)
    except ValidationError as exc:
        raise ToolError(_validation(exc)) from None
    lead.refresh_from_db()
    return {"saved": True, **_lead_summary(lead)}


def search_customer(ctx, tool, args):
    q = str(args.get("query") or "").strip()
    if len(q) < 3:
        raise ToolError("Give at least 3 characters of a phone, name, e-mail or lead ID.")
    leads = Lead.objects.filter(company=ctx.company, deleted_at__isnull=True).filter(crm.search_q(q))[:3]
    return {"customers": [_lead_summary(lead) for lead in leads.select_related("status", "company")]}


def assign_salesperson(ctx, tool, args):
    lead = _need_lead(ctx)
    reason = str(args.get("reason") or "").strip()[:200]
    if not lead.assigned_user_id:
        crm.auto_assign(lead)
        lead.refresh_from_db()
    crm.log(lead, "assignment", f"AI {ctx.employee.name} escalated to a salesperson: {reason}", actor_type="ai")
    if not lead.assigned_user_id:
        task = crm.create_task(
            ctx.company,
            {
                "title": f"Escalated by {ctx.employee.name}: {reason}",
                "due_at": timezone.now(),
                "lead": lead,
                "type": "callback",
            },
        )
        _track(ctx, "tasks", task)
        return {"assigned": False, "message": "No salesperson is free; the team has a task to call back."}
    person = lead.assigned_user.full_name or "our sales team"
    return {"assigned": True, "salesperson": person.split(" ")[0]}


def can_hand_over(conv):
    """Live calls (and the browser voice test) and the typed channels with the shared inbox (HO-01)."""
    return bool((conv.state or {}).get("voice")) or (conv.channel in Conversation.CHAT_CHANNELS and not conv.is_test)


def transfer_call(ctx, tool, args):
    """TOOL-08 / VOICE-11: hand the live call to a person. The Voice Gateway connects the caller after the AI's
    sentence (warm transfer); on chats a team member takes over in the shared inbox (apps.agents.inbox). Routing,
    no-agent handling and the log are in apps.voice.handoff."""
    if not can_hand_over(ctx.conversation):
        raise ToolError("Handing over works on calls and live chats only; use assign_salesperson here.")
    reason = str(args.get("reason") or "").strip()[:200] or "Customer asked for a person"
    why = "negative_sentiment" if reason.lower().startswith("upset") else "customer_request"  # handoff.upset_prompt
    ctx.conversation.state = {
        **(ctx.conversation.state or {}),
        "transfer": {"reason": why, "detail": reason},
    }
    ctx.conversation.save(update_fields=["state", "updated_at"])
    return {"transferring": True, "say": "Tell the customer in one short sentence that you are connecting them now."}


def schedule_callback(ctx, tool, args):
    lead = _need_lead(ctx)
    when = None
    if args.get("when"):
        day = parse_indian_date(args["when"], today(ctx.company))
        if day:
            when = dt.datetime.combine(day, dt.time(10, 0), company_tz(ctx.company))
    when = when or timezone.now() + dt.timedelta(hours=1)
    message = str(args.get("message") or "Customer asked for a callback").strip()[:500]
    task = crm.create_task(
        ctx.company,
        {"title": f"Call back: {message[:120]}", "notes": message, "due_at": when, "lead": lead, "type": "callback"},
    )
    _track(ctx, "tasks", task)
    lead.follow_up_at = when
    lead.save(update_fields=["follow_up_at", "updated_at"])
    return {"scheduled": True, "callback_at": when.astimezone(company_tz(ctx.company)).strftime("%d %b %Y %H:%M")}


def create_enquiry(ctx, tool, args):
    """TOOL-15 create_booking_enquiry: saves the details, a note, a team task and the configured lead event."""
    lead = _need_lead(ctx)
    if args.get("fields"):
        update_lead(ctx, tool, {"fields": args["fields"]})
    title = tool.config.get("title") or "Enquiry"
    details = str(args.get("details") or "").strip()[:1000]
    crm.add_note(lead, f"{title} (by {ctx.employee.name}): {details}")
    task = crm.create_task(
        ctx.company,
        {"title": f"{title}: {lead.name or lead.reference}", "notes": details, "due_at": timezone.now(), "lead": lead},
    )
    _track(ctx, "tasks", task)
    if tool.config.get("event"):
        crm.apply_event(lead, tool.config["event"], actor_type="ai")
    return {"recorded": True, "reference": lead.reference}


# ------------------------------------------------------------------ handlers: catalogue (TOOL-04, TOOL-15, CAT-03)
def catalog_search(ctx, tool, args):
    ctype = _catalog_type(ctx, tool, args)
    defs = catalog.fields(ctx.company, ctype)
    params = {"q": args.get("query") or "", "status": CatalogItem.ACTIVE, "sort": args.get("sort") or ""}
    for d in defs:
        if not d.filterable:
            continue
        for suffix in ("", "_min", "_max"):
            if args.get(d.key + suffix) not in (None, ""):
                params[f"f_{d.key}{suffix}"] = str(args[d.key + suffix])
    qs = catalog.filter_items(ctx.company, ctype, params)
    if args.get("max_price"):
        try:
            qs = qs.filter(price_paise__lte=parse_inr(args["max_price"]))
        except ValidationError as exc:
            raise ToolError(_validation(exc)) from None
    limit = min(int(args.get("limit") or 5), MAX_RESULTS)
    items = list(qs[:limit])
    return {"catalogue": ctype.name, "count": qs.count(), "items": [_item_out(ctype, i, defs) for i in items]}


def _requirement(ctx, args):
    req = dict(ctx.lead.custom) if ctx.lead else {}
    req.update({k: v for k, v in (args or {}).items() if v not in (None, "") and k != "limit"})
    if req.get("budget") not in (None, "") and not isinstance(req["budget"], int):
        try:
            req["budget"] = parse_inr(req["budget"])
        except ValidationError:
            req.pop("budget")
    return req


def catalog_match(ctx, tool, args):
    """CAT-03: rank items by budget (± tolerance), location (with nearby-area aliases), BHK, type and possession.
    Rules come from the catalogue type (template) and the company's own overrides in its catalogue settings."""
    ctype = _catalog_type(ctx, tool, args)
    defs = {d.key: d for d in catalog.fields(ctx.company, ctype)}
    rules = {**(ctype.match_rules or {}), **(ctx.company.settings.get("catalog_match", {}).get(ctype.key) or {})}
    tolerance = float(rules.get("budget_tolerance_percent", 10)) / 100
    weights = {"budget": 40, "location": 25, **(rules.get("weights") or {})}
    aliases = {k.lower(): [a.lower() for a in v] for k, v in (rules.get("location_aliases") or {}).items()}
    req = _requirement(ctx, args)
    if not any(req.get(k) not in (None, "", []) for k in ["budget", "location", *defs]):
        raise ToolError("Not enough requirement yet: ask for budget, location and the main preferences first.")
    wanted_places = set()
    if req.get("location"):
        place = str(req["location"]).lower().strip()
        wanted_places = {place, *aliases.get(place, [])}
        wanted_places |= {k for k, v in aliases.items() if place in v}
    scored = []
    for item in CatalogItem.objects.filter(company=ctx.company, catalog_type=ctype, status=CatalogItem.ACTIVE):
        points, reasons, total = 0, [], 0
        budget = req.get("budget")
        if budget and item.price_paise is not None:
            total += weights["budget"]
            if item.price_paise <= budget * (1 + tolerance):
                points += (
                    weights["budget"] if item.price_paise >= budget * (1 - 2 * tolerance) else weights["budget"] // 2
                )
                reasons.append("within budget")
            else:
                continue  # over budget + tolerance: not a match
        if wanted_places:
            total += weights["location"]
            item_place = " ".join(
                str(item.attributes.get(k, "")) for k in ("location", "address", "destinations")
            ).lower()
            if any(p and p in item_place for p in wanted_places):
                points += weights["location"]
                reasons.append("location")
        for key, d in defs.items():
            if key in ("location", "price") or key not in req or req[key] in (None, "", []):
                continue
            if d.type not in ("single_select", "multi_select", "yes_no"):
                continue
            weight = int(weights.get(key, 10))
            total += weight
            have, want = item.attributes.get(key), req[key]
            if have == want or (isinstance(have, list) and want in have):
                points += weight
                reasons.append(d.label)
        if total:
            scored.append((points / total, item, reasons))
    scored.sort(key=lambda s: -s[0])
    limit = min(int(args.get("limit") or 3), MAX_RESULTS)
    out_defs = list(defs.values())
    return {
        "matches": [
            {**_item_out(ctype, item, out_defs), "match_percent": round(score * 100), "matched_on": reasons}
            for score, item, reasons in scored[:limit]
            if score > 0
        ],
        "budget_tolerance_percent": round(tolerance * 100),
    }


def catalog_details(ctx, tool, args):
    ctype = _catalog_type(ctx, tool, args)
    item = CatalogItem.objects.filter(company=ctx.company, catalog_type=ctype, pk=_uuid(args.get("item_id"))).first()
    if not item:
        raise ToolError("Unknown item_id: search the catalogue first.")
    defs = catalog.fields(ctx.company, ctype)
    wanted = tool.config.get("fields") or [d.key for d in defs]
    out = {"item_id": str(item.pk), "title": item.title}
    if item.price_paise is not None:
        out["price"] = format_inr(item.price_paise)
    for d in defs:
        if d.key in wanted and item.attributes.get(d.key) not in (None, "", []):
            out[d.label] = field_engine.display(d, item.attributes[d.key])
    return out


# ------------------------------------------------------------------ handlers: calendar (TOOL-05, CAL-06)
def check_availability(ctx, tool, args):
    appt_type = _appointment_type(ctx, tool, args)
    day = parse_indian_date(args.get("date") or "", today(ctx.company))
    if not day:
        raise ToolError("Give the date, e.g. 2026-11-15, tomorrow or next Sunday.")
    slots = []
    for resource in _resources(ctx, appt_type):
        for start in calendar.available_slots(resource, appt_type, day):
            slots.append(
                {
                    "resource_id": str(resource.pk),
                    "with": resource.name,
                    "start": start.astimezone(calendar.tz_for(resource))
                    .replace(tzinfo=None)
                    .isoformat(timespec="minutes"),
                }
            )
    slots.sort(key=lambda s: s["start"])
    return {"date": day.isoformat(), "appointment_type": appt_type.name, "free_slots": slots[:12]}


def book_appointment(ctx, tool, args):
    lead = _need_lead(ctx)
    appt_type = _appointment_type(ctx, tool, args)
    resources = {str(r.pk): r for r in _resources(ctx, appt_type)}
    resource = resources.get(str(args.get("resource_id")))
    if not resource:
        raise ToolError("Unknown resource_id: use one returned by check_availability.")
    try:
        appt = calendar.book(
            ctx.company,
            resource,
            appt_type,
            _parse_start(args.get("start"), resource),
            lead=lead,
            created_by_type="ai",
            channel=ctx.conversation.channel,
            notes=str(args.get("notes") or "")[:500],
            notify=not ctx.conversation.is_test,
        )
    except ValidationError as exc:
        raise ToolError(f"Not booked: {_validation(exc)} Check availability again.") from None
    _track(ctx, "appointments", appt)
    return {
        "booked": True,
        "appointment_number": appt.reference,
        "type": appt_type.name,
        "with": resource.name,
        "when": appt.starts_at.astimezone(calendar.tz_for(resource)).strftime("%A %d %b %Y, %I:%M %p"),
    }


def reschedule_appointment(ctx, tool, args):
    appt = _lead_appointment(ctx, args)
    try:
        calendar.reschedule(appt, _parse_start(args.get("start"), appt.resource), notify=not ctx.conversation.is_test)
    except ValidationError as exc:
        raise ToolError(f"Not moved: {_validation(exc)}") from None
    return {
        "rescheduled": True,
        "appointment_number": appt.reference,
        "when": appt.starts_at.astimezone(calendar.tz_for(appt.resource)).strftime("%A %d %b %Y, %I:%M %p"),
    }


def cancel_appointment(ctx, tool, args):
    appt = _lead_appointment(ctx, args)
    try:
        calendar.set_status(
            appt,
            Appointment.CANCELLED,
            str(args.get("reason") or "Cancelled by the customer"),
            notify=not ctx.conversation.is_test,
        )
    except ValidationError as exc:
        raise ToolError(_validation(exc)) from None
    return {"cancelled": True, "appointment_number": appt.reference}


# ------------------------------------------------------------------ handlers: communication (TOOL-07)
def send_email(ctx, tool, args):
    """Approved templates only, to the current lead only (no free-text e-mails, no other recipients)."""
    from apps.notifications import services as notify

    lead = _need_lead(ctx)
    if not lead.email:
        raise ToolError("The customer has no e-mail address yet: ask for it and save it with update_lead.")
    key = args.get("template")
    if key not in (tool.config.get("templates") or []):
        raise ToolError("Unknown e-mail template.")
    context = {
        "lead_name": lead.name or "there",
        "company_name": ctx.company.name,
        "employee_name": ctx.employee.name,
        "summary": ctx.conversation.summary,
    }
    attachments = []
    if args.get("item_id"):
        item = (
            CatalogItem.objects.filter(company=ctx.company, pk=_uuid(args["item_id"]))
            .select_related("catalog_type")
            .first()
        )
        if not item:
            raise ToolError("Unknown item_id.")
        defs = catalog.fields(ctx.company, item.catalog_type)
        rows = [("Price", format_inr(item.price_paise))] if item.price_paise is not None else []
        rows += [(d.label, field_engine.display(d, item.attributes.get(d.key))) for d in defs]
        context["item_title"] = item.title
        context["item_details"] = format_html(
            "<ul>{}</ul>", format_html_join("", "<li><strong>{}:</strong> {}</li>", ((k, v) for k, v in rows if v))
        )
        from apps.core.storage import private_storage

        for media in item.media.filter(kind="brochure")[:2]:
            with private_storage.open(media.file_key, "rb") as fh:
                attachments.append((media.file_name, fh.read()))
    if args.get("appointment_number") or key == "ai/appointment_confirmation":
        appt = _lead_appointment(ctx, args)
        context.update(
            appointment_type=appt.appointment_type.name,
            appointment_number=appt.reference,
            appointment_time=appt.starts_at.astimezone(calendar.tz_for(appt.resource)).strftime(
                "%A %d %b %Y, %I:%M %p"
            ),
            appointment_location=appt.location or appt.resource.name,
        )
    if not notify.send(key, lead.email, context, attachments=attachments):
        raise ToolError("This e-mail template is switched off.")
    crm.log(lead, "email", f"E-mail sent by {ctx.employee.name}: {key}", actor_type="ai")
    return {"sent": True, "to": lead.email}


def send_whatsapp(ctx, tool, args):
    """TOOL-09: on a WhatsApp chat (window open) the item's photos, brochure and location; on calls and other chats
    an approved template (item information or lead follow-up). Opt-out and opt-in are checked."""
    from apps.whatsapp import services as whatsapp

    lead = _need_lead(ctx)
    if ctx.conversation.is_test:
        return {"sent": False, "note": "Test conversation: nothing was sent on WhatsApp."}
    item = None
    if args.get("item_id"):
        item = CatalogItem.objects.filter(company=ctx.company, pk=_uuid(args["item_id"])).first()
        if not item:
            raise ToolError("Unknown item_id.")
    note = str(args.get("note") or "").strip()[:500]
    try:
        if ctx.conversation.channel == "whatsapp" and item:
            return {"sent": True, "messages": whatsapp.send_item(ctx.conversation, item, note)}
        purpose = "item_info" if item else "lead_follow_up"
        template = whatsapp.find_template(ctx.company, purpose, ctx.conversation.language or lead.preferred_language)
        if not template:
            raise ToolError("No approved WhatsApp template for this yet; offer to send it by e-mail instead.")
        whatsapp.send_template(template, lead, {"employee": ctx.employee, "item": item, "text": note})
    except ValidationError as exc:
        raise ToolError(_validation(exc)) from None
    return {"sent": True, "template": template.name, "to": lead.phone}


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


# ------------------------------------------------------------------ registry of handlers and their schemas
def _s(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _schema_lead(ctx, tool, create):
    statuses = [s.key for s in templates.statuses(ctx.company)]
    props = {
        "name": {"type": "string"},
        "email": {"type": "string"},
        "fields": _fields_schema(_lead_fields(ctx)),
    }
    if create:
        props["phone"] = {
            "type": "string",
            "description": "Only if the customer gave it; the channel number is used otherwise",
        }
    else:
        props["status"] = {"type": "string", "enum": statuses}
        props["next_action"] = {"type": "string"}
    return _s(props)


def _schema_catalog(ctx, tool, match=False):
    types = templates.catalog_types(ctx.company)
    props = {}
    fixed = tool.config.get("catalog_type")
    if not fixed:
        props["catalog_type"] = {"type": "string", "enum": [t.key for t in types]}
    ctype = next((t for t in types if t.key == fixed), None) if fixed else None
    if match:
        if ctype:
            for d in catalog.fields(ctx.company, ctype):
                if d.type in ("single_select", "multi_select", "location"):
                    props[d.key] = {**_json_type(d), "description": d.label}
        props["budget"] = {"type": "string", "description": "Budget, e.g. 70 lakh"}
        props["location"] = {"type": "string"}
    else:
        props["query"] = {"type": "string", "description": "Free text, e.g. a name or area"}
        props["max_price"] = {"type": "string", "description": "e.g. 80 lakh"}
        if ctype:
            for d in catalog.fields(ctx.company, ctype):
                if not d.filterable:
                    continue
                if d.type in ("number", "currency"):
                    props[f"{d.key}_min"] = {"type": "string", "description": f"{d.label} from"}
                    props[f"{d.key}_max"] = {"type": "string", "description": f"{d.label} up to"}
                else:
                    props[d.key] = {**_json_type(d), "description": d.label}
    props["limit"] = {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS}
    return _s(props, ["catalog_type"] if not fixed else [])


def _schema_appt(ctx, tool, extra, required=()):
    props = dict(extra)
    if not tool.config.get("appointment_type"):
        props["appointment_type"] = {
            "type": "string",
            "enum": [t.key for t in templates.appointment_types(ctx.company)],
        }
        required = (*required, "appointment_type")
    return _s(props, required)


HANDLERS = {
    # handler key: (function, schema builder)
    "create_lead": (create_lead, lambda ctx, t: _schema_lead(ctx, t, True)),
    "update_lead": (update_lead, lambda ctx, t: _schema_lead(ctx, t, False)),
    "search_customer": (search_customer, lambda ctx, t: _s({"query": {"type": "string"}}, ["query"])),
    "catalog_search": (catalog_search, lambda ctx, t: _schema_catalog(ctx, t)),
    "catalog_match": (catalog_match, lambda ctx, t: _schema_catalog(ctx, t, match=True)),
    "catalog_details": (
        catalog_details,
        lambda ctx, t: _s(
            {
                "item_id": {"type": "string"},
                **({} if t.config.get("catalog_type") else {"catalog_type": {"type": "string"}}),
            },
            ["item_id"],
        ),
    ),
    "check_availability": (
        check_availability,
        lambda ctx, t: _schema_appt(
            ctx, t, {"date": {"type": "string", "description": "e.g. 2026-11-15 or tomorrow"}}, ("date",)
        ),
    ),
    "book_appointment": (
        book_appointment,
        lambda ctx, t: _schema_appt(
            ctx,
            t,
            {"resource_id": {"type": "string"}, "start": {"type": "string"}, "notes": {"type": "string"}},
            ("resource_id", "start"),
        ),
    ),
    "reschedule_appointment": (
        reschedule_appointment,
        lambda ctx, t: _s({"appointment_number": {"type": "string"}, "start": {"type": "string"}}, ["start"]),
    ),
    "cancel_appointment": (
        cancel_appointment,
        lambda ctx, t: _s({"appointment_number": {"type": "string"}, "reason": {"type": "string"}}, ["reason"]),
    ),
    "assign_salesperson": (assign_salesperson, lambda ctx, t: _s({"reason": {"type": "string"}}, ["reason"])),
    "transfer_call": (transfer_call, lambda ctx, t: _s({"reason": {"type": "string"}}, ["reason"])),
    "schedule_callback": (
        schedule_callback,
        lambda ctx, t: _s({"when": {"type": "string"}, "message": {"type": "string"}}, ["message"]),
    ),
    "send_whatsapp": (
        send_whatsapp,
        lambda ctx, t: _s({"item_id": {"type": "string"}, "note": {"type": "string"}}, []),
    ),
    "send_email": (
        send_email,
        lambda ctx, t: _s(
            {
                "template": {"type": "string", "enum": t.config.get("templates") or []},
                "item_id": {"type": "string"},
                "appointment_number": {"type": "string"},
            },
            ["template"],
        ),
    ),
    "create_enquiry": (
        create_enquiry,
        lambda ctx, t: _s({"details": {"type": "string"}, "fields": _fields_schema(_lead_fields(ctx))}, ["details"]),
    ),
}
HANDLER_CHOICES = [(k, k.replace("_", " ").capitalize()) for k in HANDLERS]

# Always available to every AI Employee; the runtime turns it into the configured fallback (ENG-04, KB-10).
CANNOT_ANSWER = {
    "name": "cannot_answer",
    "description": "Call this when the customer asks for a fact (price, availability, policy, specification …) "
    "that is not in your knowledge or tool results. Never guess.",
    "parameters": _s({"question": {"type": "string"}, "reason": {"type": "string"}}, ["question"]),
}


# ------------------------------------------------------------------ which tools an employee has (TOOL-13)
def available(employee):
    """Tools the employee may switch on: active in the registry, allowed for its industry and role, enabled in its
    industry template and role."""
    version = employee.template_version
    allowed_template = set(version.enabled_tools) if version and version.enabled_tools else None
    allowed_role = set(employee.role.allowed_tools or []) or None
    qs = Tool.objects.filter(is_active=True).filter(Q(industries__isnull=True) | Q(industries=employee.industry_id))
    out = []
    for tool in qs.distinct():
        if tool.role_keys and employee.role.key not in tool.role_keys:
            continue
        if allowed_template is not None and tool.key not in allowed_template:
            continue
        if allowed_role is not None and tool.key not in allowed_role:
            continue
        if tool.handler in HANDLERS:
            out.append(tool)
    return out


def enabled(employee):
    return [t for t in available(employee) if employee.tools.get(t.key, True)]


def definitions(ctx, tools):
    """What the model sees (layer 8 of the prompt)."""
    out = []
    live = can_hand_over(ctx.conversation)
    for tool in tools:
        if tool.handler == "transfer_call" and not live:  # only offered on calls and live chats
            continue
        schema = _schema_or_none(ctx, tool)
        if schema is not None:
            out.append({"name": tool.key, "description": tool.description, "parameters": schema})
    return out + [CANNOT_ANSWER]


def _schema_or_none(ctx, tool):
    """A tool that cannot build its schema (e.g. its catalogue type is missing) is left out, not fatal."""
    try:
        return HANDLERS[tool.handler][1](ctx, tool)
    except Exception:  # noqa: BLE001
        log.warning("tool %s skipped: schema could not be built", tool.key, exc_info=True)
        return None


# ------------------------------------------------------------------ execution (ENG-03, TOOL-14, SEC-14)
def run(ctx, tools, name, args, call_id=""):
    """Validate, execute and log one tool call. → result dict (always JSON-serialisable)."""
    tool = next((t for t in tools if t.key == name), None)
    key = (
        f"{ctx.conversation.pk}:{ctx.turn}:{name}:"
        + hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:24]
    )
    previous = ToolInvocation.objects.filter(company=ctx.company, idempotency_key=key).first()
    if previous:  # same call retried within this turn: return the first result, never run a write twice
        return previous.output
    started = time.monotonic()
    status = ToolInvocation.OK
    if not tool:
        status, output = ToolInvocation.DENIED, {"error": f"Tool {name} is not available to you."}
    elif ctx.conversation.tool_calls >= setting("ai.max_tool_calls_per_conversation"):
        status, output = ToolInvocation.DENIED, {"error": "Tool limit reached for this conversation."}
    else:
        schema = HANDLERS[tool.handler][1](ctx, tool)
        errors = sorted(Draft7Validator(schema).iter_errors(args or {}), key=lambda e: e.path)
        if errors:
            status, output = (
                ToolInvocation.ERROR,
                {"error": "Invalid arguments: " + "; ".join(e.message for e in errors[:3])},
            )
        else:
            try:
                with transaction.atomic():
                    output = HANDLERS[tool.handler][0](ctx, tool, args or {})
            except ToolError as exc:
                status, output = ToolInvocation.ERROR, {"error": str(exc)}
    latency = int((time.monotonic() - started) * 1000)
    if tool and status == ToolInvocation.OK and latency > tool.timeout_ms:
        # ponytail: handlers run in-process, so a slow call is flagged after the fact rather than cut off
        status = ToolInvocation.TIMEOUT
    output = json.loads(json.dumps(output, default=str))
    try:
        ToolInvocation.objects.create(
            company=ctx.company,
            conversation=ctx.conversation,
            tool_key=name,
            input=args or {},
            output=output,
            status=status,
            latency_ms=latency,
            idempotency_key=key,
        )
    except IntegrityError:
        pass
    ctx.conversation.tool_calls += 1
    ctx.conversation.save(update_fields=["tool_calls", "state", "updated_at"])
    return output
