"""CRM business logic (CRM-01 … CRM-18, SCORE-02). Views, APIs, imports and (Phase 4) AI tools all call these.

Every function receives the company explicitly (from request.company or the lead) — never from user input.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.models import phone_validator
from apps.audit.services import record
from apps.core.india import normalise_phone
from apps.core.money import parse_inr
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.industries.models import LeadSource
from apps.platform_config import services as config
from apps.rbac.services import has_perm
from apps.tenancy.context import platform_context
from apps.tenancy.models import Membership

from .models import AssignmentRule, Lead, LeadActivity, LeadCounter, LeadNote, LeadScoreEvent, Task

CORE_FIELDS = [
    "name",
    "phone",
    "email",
    "source",
    "status",
    "assigned_user",
    "preferred_language",
    "tags",
    "follow_up_at",
    "next_action",
    "dnd",
    "consent_status",
]


class DuplicateLead(ValidationError):
    def __init__(self, lead):
        self.lead = lead
        super().__init__(f"A lead with this phone or email already exists: {lead.reference} {lead.name}".strip())


# ------------------------------------------------------------------ helpers
def log(lead, type, summary, user=None, actor_type="user", **data):
    return LeadActivity.objects.create(
        company_id=lead.company_id,
        lead=lead,
        type=type,
        summary=summary[:500],
        data=data,
        actor=user if user and user.is_authenticated else None,
        actor_type=actor_type,
    )


def status_by_key(company, key):
    for s in templates.statuses(company):
        if s.key == key:
            return s
    raise ValidationError(f"Unknown lead status: {key}.")


def default_status(company):
    statuses = templates.statuses(company)
    if not statuses:
        raise ValidationError("No lead statuses are configured.")
    return next((s for s in statuses if s.key == "new"), statuses[0])


def custom_field_limit(company):
    """CRM-04: how many own lead fields the company's plan allows (None = not limited)."""
    from apps.billing.models import PlanEntitlement

    row = PlanEntitlement.objects.filter(plan_id=company.plan_id, key="custom_fields").first()
    return row.limit_value if row else None


def members(company):
    """Active users of the company (assignment targets)."""
    with platform_context():
        return [
            m.user
            for m in Membership.all_companies.filter(company=company, status=Membership.ACTIVE)
            .select_related("user")
            .order_by("user__full_name", "user__email")
        ]


def _member(company, user_or_id):
    if user_or_id in (None, ""):
        return None
    uid = str(getattr(user_or_id, "pk", user_or_id))
    user = next((u for u in members(company) if str(u.pk) == uid), None)
    if not user:
        raise ValidationError("Leads can only be assigned to active members of your team.")
    return user


def visible(request, include_deleted=False):
    """Leads the signed-in user may see: all of them with leads.view_all, else only the ones assigned to them."""
    qs = Lead.objects.select_related("status", "source", "assigned_user")
    if not include_deleted:
        qs = qs.filter(deleted_at__isnull=True)
    if not has_perm(request.user, "leads.view_all", request.company):
        qs = qs.filter(assigned_user=request.user)
    return qs


def find_duplicate(company, phone="", email="", exclude=None):
    q = Q()
    if phone:
        q |= Q(phone=phone)
    if email:
        q |= Q(email__iexact=email)
    if not q:
        return None
    qs = Lead.all_companies.filter(company=company, deleted_at__isnull=True).filter(q)
    if exclude:
        qs = qs.exclude(pk=exclude.pk)
    return qs.first()


def _next_numbers(company, count=1):
    counter, _ = LeadCounter.all_companies.get_or_create(company=company)
    counter = LeadCounter.all_companies.select_for_update().get(pk=counter.pk)
    start = counter.value + 1
    counter.value += count
    counter.save(update_fields=["value", "updated_at"])
    return range(start, start + count)


# ------------------------------------------------------------------ validation
def clean_core(company, data, partial=False, cache=None):
    """CRM-01 common fields → model values. Raises ValidationError with readable messages.
    `cache` (a dict) keeps status / source lookups between calls, e.g. for imports."""
    out, errors = {}, []
    cache = {} if cache is None else cache

    def has(key):
        return key in data and not (partial and data[key] is None)

    if has("name"):
        out["name"] = str(data.get("name") or "").strip()[:150]
    if has("phone"):
        phone = str(data.get("phone") or "").strip()
        if phone:
            phone = normalise_phone(phone)
            try:
                phone_validator(phone)
            except ValidationError:
                errors.append(f"Phone {data.get('phone')!r} is not a valid number.")
        out["phone"] = phone
    if has("email"):
        email = str(data.get("email") or "").strip().lower()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors.append(f"Email {email!r} is not valid.")
        out["email"] = email
    if has("source"):
        src = data.get("source")
        if src in (None, ""):
            out["source"] = None
        elif isinstance(src, LeadSource):
            out["source"] = src
        else:
            if "sources" not in cache:
                cache["sources"] = {}
                for source in LeadSource.objects.filter(is_active=True):
                    cache["sources"][source.key.lower()] = cache["sources"][source.label.lower()] = source
            out["source"] = cache["sources"].get(str(src).strip().lower())
            if not out["source"]:
                errors.append(f"Unknown lead source: {src}.")
    if has("status") and data.get("status"):
        status = data["status"]
        if hasattr(status, "category"):
            out["status"] = status
        else:
            if "statuses" not in cache:
                cache["statuses"] = {}
                for st in templates.statuses(company):
                    cache["statuses"][st.key] = cache["statuses"][st.label.lower()] = st
            out["status"] = cache["statuses"].get(str(status).strip()) or cache["statuses"].get(
                str(status).strip().lower()
            )
            if not out["status"]:
                errors.append(f"Unknown lead status: {status}.")
    if has("assigned_user"):
        try:
            out["assigned_user"] = _member(company, data.get("assigned_user"))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if has("preferred_language"):
        out["preferred_language"] = str(data.get("preferred_language") or "")[:10]
    if has("tags"):
        tags = data.get("tags") or []
        tags = tags if isinstance(tags, list) else str(tags).split(",")
        out["tags"] = sorted({str(t).strip() for t in tags if str(t).strip()})
    if has("follow_up_at"):
        value = data.get("follow_up_at")
        if value and isinstance(value, str):
            parsed = parse_datetime(value)
            if not parsed:
                errors.append("Follow-up date: use YYYY-MM-DD HH:MM.")
            value = parsed
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value)
        out["follow_up_at"] = value or None
    if has("next_action"):
        out["next_action"] = str(data.get("next_action") or "")[:255]
    if has("dnd"):
        out["dnd"] = bool(data.get("dnd"))
    if has("consent_status"):
        if data.get("consent_status") not in dict(Lead.CONSENT):
            errors.append("Consent: unknown value.")
        out["consent_status"] = data.get("consent_status")
    if not partial and not (out.get("name") or out.get("phone") or out.get("email")):
        errors.append("Enter at least a name, phone or email.")
    if errors:
        raise ValidationError(errors)
    return out


def clean_custom(company, data, partial=False):
    return field_engine.clean_values(templates.fields_for(company, "lead"), data or {}, partial=partial)


# ------------------------------------------------------------------ scoring (SCORE-02) and assignment (CRM-15)
def _lead_value(lead, field):
    key = field[7:] if field.startswith("custom.") else field
    if key in ("name", "phone", "email", "preferred_language", "next_action"):
        return getattr(lead, key)
    if key == "source":
        return lead.source.key if lead.source_id else None
    if key == "tags":
        return lead.tags
    return (lead.custom or {}).get(key)


def matches(lead, condition, defs=None):
    """One rule condition: {"event": …} | {"status": …} | {"field", "op", "value"}."""
    if not condition:
        return False
    if "event" in condition:
        return condition["event"] in (lead.events or [])
    if "status" in condition:
        return bool(lead.status_id) and lead.status.key == condition["status"]
    value, op, target = (
        _lead_value(lead, condition.get("field", "")),
        condition.get("op", "present"),
        condition.get("value"),
    )
    present = value not in (None, "", [], {})
    if op == "present":
        return present
    if not present:
        return False
    values = value if isinstance(value, list) else [value]
    if op in ("eq", "neq"):
        hit = any(str(v).strip().lower() == str(target).strip().lower() for v in values)
        return hit if op == "eq" else not hit
    if op == "contains":
        return any(str(target).strip().lower() in str(v).lower() for v in values)
    defn = (defs or {}).get(condition.get("field", "").removeprefix("custom."))
    try:
        number = parse_inr(target) if defn is not None and defn.type == "currency" else float(target)
        current = float(value)
    except (TypeError, ValueError, ValidationError):
        return False
    return {"gt": current > number, "gte": current >= number, "lt": current < number, "lte": current <= number}.get(
        op, False
    )


def scoring_context(company):
    """Everything scoring and assignment need, loaded once (reuse it for many leads, e.g. imports)."""
    return {
        "defs": {d.key: d for d in templates.fields_for(company, "lead")},
        "rules": templates.scoring_rules(company),
        "limits": templates.thresholds(company),
        "members": {str(u.pk): u for u in members(company)},
    }


def compute_score(lead, company, ctx=None):
    """→ (value 0-100, label, reason, rule hits). A forced label (e.g. not interested → cold) wins."""
    ctx = ctx or scoring_context(company)
    defs = ctx["defs"]
    hits = [r for r in ctx["rules"] if matches(lead, r.condition, defs)]
    value = max(0, min(100, sum(r.points for r in hits)))
    reason = ", ".join(r.name for r in hits)
    if lead.ai_intent_score is not None:  # SCORE-03: AI intent blended with the rules (weight in AI settings)
        weight = config.get("ai.intent_weight_percent") / 100
        value = round(value * (1 - weight) + lead.ai_intent_score * weight)
        reason = "; ".join(x for x in (reason, f"AI: {lead.ai_intent_reason}" if lead.ai_intent_reason else "") if x)
    forced = next((r.force_label for r in hits if r.force_label), "")
    limits = ctx["limits"]
    label = forced or (Lead.HOT if value >= limits["hot"] else Lead.WARM if value >= limits["warm"] else Lead.COLD)
    return value, label, reason, [r.key for r in hits]


def rescore(lead, user=None, source="rules"):
    value, label, reason, hits = compute_score(lead, lead.company)
    if (value, label) == (lead.score_value, lead.score_label):
        return False
    old = lead.score_label
    lead.score_value, lead.score_label, lead.score_reason = value, label, reason[:500]
    lead.save(update_fields=["score_value", "score_label", "score_reason", "updated_at"])
    LeadScoreEvent.objects.create(
        company_id=lead.company_id,
        lead=lead,
        label=label,
        value=value,
        reason=reason[:500],
        rule_hits=hits,
        source=source,
    )
    log(lead, "score_change", f"Score {value} ({label}{f', was {old}' if old else ''})", user, actor_type="system")
    if label == Lead.HOT and old != Lead.HOT:
        hot_lead_actions(lead, user)
    return True


HOT_KEYS = {"notify": "crm.hot_lead_notify", "assign": "crm.hot_lead_assign"}


def hot_policy(company):
    """SCORE-05: what happens when a lead becomes hot — the company's choice or the platform default. (Handing the
    live call / chat to a person is a rule per AI Employee.)"""
    own = (company.settings or {}).get("hot_lead") or {}
    return {k: bool(own[k]) if k in own else config.get(s) for k, s in HOT_KEYS.items()}


def save_hot_policy(company, data, user=None, request=None):
    own = {k: data[k] in (True, "on", "true", "1", 1) for k in HOT_KEYS if k in data}
    company.settings = {**(company.settings or {}), "hot_lead": own}
    company.save(update_fields=["settings", "updated_at"])
    record(request, "crm.hot_lead_policy", "company", company.pk, own, user, company=company)
    return hot_policy(company)


def hot_lead_actions(lead, user=None):
    """SCORE-05: assign a salesperson (assignment rules) and alert the people who should call back."""
    from django.urls import reverse

    from apps.notifications import alerts

    rules = hot_policy(lead.company)
    if rules["assign"] and not lead.assigned_user_id:
        auto_assign(lead, user)
    if not rules["notify"]:
        return []
    people = [lead.assigned_user] if lead.assigned_user_id else alerts.people_with(lead.company, "leads.assign")
    people = [p for p in people if not (user and p.pk == user.pk)]  # not the person who made the change
    url = reverse("panel:lead_detail", args=[lead.pk])
    return alerts.notify(
        lead.company,
        people,
        "hot_lead",
        f"Hot lead: {lead.name or lead.reference} — score {lead.score_value}",
        lead.score_reason,
        url,
        email=(
            "alerts/hot_lead",
            {
                "lead_name": lead.name,
                "lead_reference": lead.reference,
                "lead_phone": lead.phone,
                "score": lead.score_value,
                "reason": lead.score_reason,
                "url": f"{settings.PUBLIC_BASE_URL}{url}",
            },
        ),
        data={"lead": str(lead.pk)},
    )


def pick_assignee(company, lead, rules=None, ctx=None):
    """First matching active rule decides; round robin rotates through its targets."""
    ctx = ctx or scoring_context(company)
    defs, member_ids = ctx["defs"], ctx["members"]
    for rule in rules if rules is not None else AssignmentRule.all_companies.filter(company=company, is_active=True):
        if rule.condition and not matches(lead, rule.condition, defs):
            continue
        targets = [member_ids[t] for t in rule.targets if t in member_ids]
        if not targets:
            continue
        if rule.strategy == "user":
            return targets[0], rule
        rule.last_index = (rule.last_index + 1) % len(targets)
        return targets[rule.last_index], rule
    return None, None


def auto_assign(lead, user=None):
    with transaction.atomic():
        rules = list(
            AssignmentRule.all_companies.select_for_update().filter(company_id=lead.company_id, is_active=True)
        )
        assignee, rule = pick_assignee(lead.company, lead, rules)
        if assignee:
            rule.save(update_fields=["last_index", "updated_at"])
            lead.assigned_user = assignee
            lead.save(update_fields=["assigned_user", "updated_at"])
            log(
                lead,
                "assignment",
                f"Assigned to {assignee.full_name or assignee.email} by rule “{rule.name}”",
                user,
                actor_type="system",
            )
    return assignee


# ------------------------------------------------------------------ create / update / status / events
@transaction.atomic
def create_lead(company, data, user=None, created_via="manual", request=None, allow_duplicate=False):
    core = clean_core(company, data)
    custom = clean_custom(company, data.get("custom"))
    duplicate = find_duplicate(company, core.get("phone", ""), core.get("email", ""))
    same_phone = bool(duplicate and core.get("phone") and duplicate.phone == core["phone"])
    if duplicate and (not allow_duplicate or same_phone):  # a phone number is unique per company
        raise DuplicateLead(duplicate)
    core.setdefault("status", default_status(company))
    lead = Lead(company=company, number=_next_numbers(company)[0], custom=custom, created_via=created_via, **core)
    lead.score_value, lead.score_label, lead.score_reason, _ = compute_score(lead, company)
    lead.save()
    log(lead, "created", f"Lead created ({lead.get_created_via_display()})", user)
    if not lead.assigned_user_id:
        auto_assign(lead, user)
    record(request, "lead.create", "lead", lead.id, company=company)
    return lead


@transaction.atomic
def update_lead(lead, data, user=None, request=None):
    company = lead.company
    core = clean_core(company, {k: v for k, v in data.items() if k in CORE_FIELDS}, partial=True)
    if "phone" in core or "email" in core:
        duplicate = find_duplicate(company, core.get("phone", ""), core.get("email", ""), exclude=lead)
        if duplicate:
            raise DuplicateLead(duplicate)
    changes = []
    new_status = core.pop("status", None)
    new_user = core.pop("assigned_user", lead.assigned_user) if "assigned_user" in core else lead.assigned_user
    for key, value in core.items():
        if getattr(lead, key) != value:
            changes.append(key)
            setattr(lead, key, value)
    if "custom" in data:
        custom = {**lead.custom, **clean_custom(company, data["custom"], partial=True)}
        if custom != lead.custom:
            changes.append("custom")
            lead.custom = custom
    lead.save()
    if changes:
        log(lead, "update", f"Updated {', '.join(c.replace('_', ' ') for c in changes)}", user)
    if "dnd" in changes or "consent_status" in changes:  # COMP-02: a consent record for every change
        opted_out = lead.dnd or lead.consent_status == "opted_out"
        _consent_row(lead, "voice" if "dnd" in changes else "all", "opt_out" if opted_out else "opt_in", "panel", user)
    if new_user != lead.assigned_user:
        assign(lead, new_user, user, request=request)
    if new_status and new_status.pk != lead.status_id:
        set_status(lead, new_status, user, request=request)
    rescore(lead, user)
    record(request, "lead.update", "lead", lead.id, company=company, changes={"fields": changes})
    return lead


def _consent_row(lead, channel, action, source, user=None, evidence=None):
    from .models import ConsentRecord

    ConsentRecord.objects.create(
        company_id=lead.company_id, lead=lead, channel=channel, action=action, source=source, evidence=evidence or {}
    )
    log(lead, "consent", f"{'Opted out of' if action == 'opt_out' else 'Opted in to'} {channel} ({source})", user)


def record_consent(lead, channel, action, source, user=None, evidence=None):
    """COMP-02: consent / opt-out per lead and channel with source and time. A voice or overall opt-out also sets
    Do-not-call, so no outbound call is placed afterwards (COMP-03)."""
    if action not in ("opt_in", "opt_out"):
        raise ValidationError("Consent action must be opt_in or opt_out.")
    fields = []
    if action == "opt_out" and channel in ("voice", "all") and not lead.dnd:
        lead.dnd = True
        fields.append("dnd")
    if channel == "all":
        lead.consent_status = "opted_out" if action == "opt_out" else "opted_in"
        fields.append("consent_status")
    elif action == "opt_in" and lead.consent_status == "unknown":
        lead.consent_status = "opted_in"
        fields.append("consent_status")
    if fields:
        lead.save(update_fields=[*fields, "updated_at"])
    _consent_row(lead, channel, action, source, user, evidence)
    return lead


def set_status(lead, status, user=None, actor_type="user", request=None):
    if isinstance(status, str):
        status = status_by_key(lead.company, status)
    old = lead.status
    if old.pk == status.pk:
        return lead
    lead.status = status
    lead.save(update_fields=["status", "updated_at"])
    log(
        lead,
        "status_change",
        f"Status {old.label} → {status.label}",
        user,
        actor_type=actor_type,
        old=old.key,
        new=status.key,
    )
    rescore(lead, user)
    record(request, "lead.status", "lead", lead.id, company=lead.company, changes={"old": old.key, "new": status.key})
    return lead


def apply_event(lead, event, user=None, actor_type="system"):
    """CRM-02 automatic transitions and SCORE-02 event rules (appointment booked, call connected … AI events)."""
    if event not in lead.events:
        lead.events = [*lead.events, event]
        lead.save(update_fields=["events", "updated_at"])
    key = templates.status_for_event(lead.company, event)
    if key:
        try:
            set_status(lead, key, user, actor_type=actor_type)
        except ValidationError:
            pass  # the template points at a status this company does not have
    rescore(lead, user)


def assign(lead, assignee, user=None, request=None):
    assignee = _member(lead.company, assignee) if assignee else None
    if lead.assigned_user_id == (assignee.pk if assignee else None):
        return lead
    lead.assigned_user = assignee
    lead.save(update_fields=["assigned_user", "updated_at"])
    who = (assignee.full_name or assignee.email) if assignee else "nobody"
    log(lead, "assignment", f"Assigned to {who}", user)
    record(request, "lead.assign", "lead", lead.id, company=lead.company)
    return lead


def soft_delete(lead, user=None, request=None):
    lead.deleted_at = timezone.now()
    lead.save(update_fields=["deleted_at", "updated_at"])
    record(request, "lead.delete", "lead", lead.id, company=lead.company)


def restore(lead, user=None, request=None):
    if find_duplicate(lead.company, lead.phone, lead.email, exclude=lead):
        raise ValidationError("Another lead now uses this phone or email. Merge them instead.")
    lead.deleted_at = None
    lead.merged_into = None
    lead.save(update_fields=["deleted_at", "merged_into", "updated_at"])
    log(lead, "update", "Lead restored", user)
    record(request, "lead.restore", "lead", lead.id, company=lead.company)


def add_note(lead, body, user=None, request=None):
    body = (body or "").strip()
    if not body:
        raise ValidationError("Write a note first.")
    note = LeadNote.objects.create(company_id=lead.company_id, lead=lead, author=user, body=body)
    log(lead, "note", body[:200], user)
    return note


def schedule_follow_up(lead, when, next_action="", user=None, with_task=True, request=None):
    """CRM-11 follow-up scheduler: sets the follow-up date / next action and creates a task for the assignee."""
    data = clean_core(lead.company, {"follow_up_at": when, "next_action": next_action}, partial=True)
    lead.follow_up_at, lead.next_action = data["follow_up_at"], data["next_action"]
    lead.save(update_fields=["follow_up_at", "next_action", "updated_at"])
    log(
        lead,
        "follow_up",
        f"Follow-up {timezone.localtime(lead.follow_up_at):%d %b %Y %H:%M}"
        + (f": {lead.next_action}" if lead.next_action else ""),
        user,
    )
    if with_task and lead.follow_up_at:
        create_task(
            lead.company,
            {
                "lead": lead,
                "title": lead.next_action or f"Follow up {lead.reference}",
                "due_at": lead.follow_up_at,
                "assigned_user": lead.assigned_user or user,
                "type": "follow_up",
            },
            user,
        )
    return lead


# ------------------------------------------------------------------ duplicates & merge (CRM-14)
def duplicate_groups(company):
    """Groups of non-deleted leads sharing an email (a phone number is already unique per company)."""
    leads = list(
        Lead.objects.filter(company=company, deleted_at__isnull=True).select_related("status").order_by("created_at")
    )
    groups, seen = [], set()
    by_email = {}
    for lead in leads:
        if lead.email:
            by_email.setdefault(lead.email.lower(), []).append(lead)
    for key, items in by_email.items():
        if len(items) > 1:
            ids = frozenset(i.pk for i in items)
            if ids not in seen:
                seen.add(ids)
                groups.append({"key": key, "leads": items})
    return groups


@transaction.atomic
def merge(primary, others, user=None, request=None):
    from .models import ConsentRecord

    others = [o for o in others if o.pk != primary.pk and o.company_id == primary.company_id]
    if not others:
        raise ValidationError("Choose at least one other lead to merge.")
    for other in others:
        for model in (LeadNote, LeadActivity, Task, LeadScoreEvent, ConsentRecord):
            model.objects.filter(lead=other).update(lead=primary)
        other.deleted_at = timezone.now()
        other.merged_into = primary
        other.save(update_fields=["deleted_at", "merged_into", "updated_at"])
        for field in ("name", "phone", "email", "preferred_language", "next_action"):
            if not getattr(primary, field) and getattr(other, field):
                setattr(primary, field, getattr(other, field))
        primary.custom = {**other.custom, **{k: v for k, v in primary.custom.items() if v not in (None, "", [])}}
        primary.tags = sorted(set(primary.tags) | set(other.tags))
        primary.events = sorted(set(primary.events) | set(other.events))
        if not primary.assigned_user_id:
            primary.assigned_user_id = other.assigned_user_id
        log(primary, "merge", f"Merged {other.reference} {other.name}".strip(), user, merged=str(other.pk))
    primary.save()
    rescore(primary, user)
    record(
        request,
        "lead.merge",
        "lead",
        primary.id,
        company=primary.company,
        changes={"merged": [str(o.pk) for o in others]},
    )
    return primary


# ------------------------------------------------------------------ bulk actions (CRM-17)
def bulk(company, leads, action, value=None, user=None, request=None):
    leads = list(leads)
    if action == "add_to_campaign":  # CAMP-01: leads picked in the lead list
        from apps.campaigns import services as campaigns
        from apps.campaigns.models import Campaign

        campaign = Campaign.objects.filter(company=company, pk=value or None).first() if value else None
        if not campaign:
            raise ValidationError("Choose a draft campaign (Campaigns → New campaign).")
        added, _ = campaigns.add_leads(campaign, leads, user, request)
        return added
    with transaction.atomic():
        for lead in leads:
            if action == "assign":
                assign(lead, value or None, user, request=request)
            elif action == "status":
                set_status(lead, value, user, request=request)
            elif action == "tag":
                tag = str(value or "").strip()
                if not tag:
                    raise ValidationError("Enter a tag.")
                if tag not in lead.tags:
                    lead.tags = sorted([*lead.tags, tag])
                    lead.save(update_fields=["tags", "updated_at"])
            elif action == "delete":
                soft_delete(lead, user, request=request)
            else:
                raise ValidationError("Unknown bulk action.")
    record(
        request,
        f"lead.bulk_{action}",
        "lead",
        ",".join(str(lead.pk) for lead in leads)[:200],
        company=company,
        changes={"count": len(leads), "value": str(value or "")},
    )
    return len(leads)


# ------------------------------------------------------------------ tasks (CRM-16)
def create_task(company, data, user=None, request=None):
    title = str(data.get("title") or "").strip()
    due = data.get("due_at")
    if isinstance(due, str):
        due = parse_datetime(due)
    if not title or not due:
        raise ValidationError("A task needs a title and a due date.")
    if timezone.is_naive(due):
        due = timezone.make_aware(due)
    assignee = _member(company, data.get("assigned_user")) if data.get("assigned_user") else user
    lead = data.get("lead")
    minutes = config.get("crm.task_reminder_minutes")
    task = Task.objects.create(
        company=company,
        lead=lead,
        title=title[:200],
        notes=str(data.get("notes") or ""),
        due_at=due,
        remind_at=due - timezone.timedelta(minutes=minutes) if minutes else None,
        type=data.get("type") or "follow_up",
        assigned_user=assignee,
        created_by=user if user and user.is_authenticated else None,
    )
    if lead:
        log(lead, "task", f"Task “{task.title}” due {timezone.localtime(due):%d %b %H:%M}", user)
    return task


def complete_task(task, user=None):
    task.status, task.completed_at = Task.DONE, timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    if task.lead_id:
        log(task.lead, "task", f"Task done: {task.title}", user)


def due_reminders(now=None):
    """Open tasks whose reminder time has come (sent by the send_task_reminders command)."""
    now = now or timezone.now()
    return Task.all_companies.filter(
        status=Task.OPEN, remind_at__lte=now, reminded_at__isnull=True, assigned_user__isnull=False
    ).select_related("assigned_user", "lead", "company")


# ------------------------------------------------------------------ export (CRM-13)
def export_rows(company, leads):
    defs = templates.fields_for(company, "lead")
    header = [
        "Lead ID",
        "Name",
        "Phone",
        "Email",
        "Source",
        "Status",
        "Score",
        "Score label",
        "Assigned to",
        "Tags",
        "Follow-up",
        "Next action",
        "Created",
    ] + [d.label for d in defs]
    rows = [header]
    for lead in leads:
        rows.append(
            [
                lead.reference,
                lead.name,
                lead.phone,
                lead.email,
                lead.source.label if lead.source_id else "",
                lead.status.label,
                lead.score_value,
                lead.get_score_label_display(),
                (lead.assigned_user.email if lead.assigned_user_id else ""),
                ", ".join(lead.tags),
                timezone.localtime(lead.follow_up_at).strftime("%Y-%m-%d %H:%M") if lead.follow_up_at else "",
                lead.next_action,
                timezone.localtime(lead.created_at).strftime("%Y-%m-%d %H:%M"),
            ]
            + [field_engine.display(d, lead.custom.get(d.key)) for d in defs]
        )
    return rows


def export(company, leads, fmt="csv", user=None, request=None):
    """Returns (bytes, content type, extension). Permission-controlled by the caller; always audit-logged."""
    limit = config.get("crm.export_max_rows")
    leads = list(leads[: limit + 1])
    if len(leads) > limit:
        raise ValidationError(f"Exports are limited to {limit} rows. Narrow the filters.")
    rows = export_rows(company, leads)
    record(
        request,
        "lead.export",
        "lead",
        f"{len(leads)} rows",
        company=company,
        category="security",
        changes={"format": fmt, "rows": len(leads)},
    )
    from apps.core.tabular import write_table

    return write_table(rows, "xlsx" if fmt == "xlsx" else "csv", "Leads")


# ------------------------------------------------------------------ global search (CP-04)
def search_q(q):
    """Name, email, phone digits or lead number (LD-000123 / 123)."""
    q = (q or "").strip()
    digits = "".join(ch for ch in q if ch.isdigit())
    cond = Q(name__icontains=q) | Q(email__icontains=q)
    if len(digits) >= 4:
        cond |= Q(phone__contains=digits)
    number = q.upper().removeprefix(config.get("crm.lead_number_prefix").upper()).lstrip("0")
    if number.isdigit():
        cond |= Q(number=int(number))
    return cond


def search(request, q, limit=10):
    if len((q or "").strip()) < 2:
        return []
    return list(visible(request).filter(search_q(q))[:limit])
