"""AI Employee management (M06: EMP-01 … EMP-14, SA-08). Panels and the REST API both call these functions."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.audit.services import record
from apps.billing import limits
from apps.industries.models import Industry
from apps.platform_config.registry import LANGUAGES
from apps.platform_config.services import get as setting
from apps.roles_tools.models import EmployeeRole
from apps.scheduling.models import Appointment, Resource
from apps.tenancy.context import company_context

from . import tools as toolkit
from .models import AIEmployee, ConfigVersion, Conversation

LANGUAGE_CODES = [code for code, _ in LANGUAGES]
CONFIG_FIELDS = [
    "name",
    "industry_id",
    "role_id",
    "template_version_id",
    "avatar",
    "persona",
    "greetings",
    "primary_language",
    "languages",
    "voices",
    "rules",
    "qualification",
    "tools",
    "calendar_resources",
]
WIZARD_STEPS = [
    ("industry", "Industry"),
    ("role", "Employee type"),
    ("identity", "Name & persona"),
    ("voice", "Voice"),
    ("languages", "Languages"),
    ("knowledge", "Knowledge"),
    ("tools", "Tools"),
    ("rules", "Rules"),
    ("test", "Test"),
    ("activate", "Activate"),
]
TEXT_LIST_RULES = ("escalation_triggers", "restricted_topics")
TRANSLATED_RULES = ("fallback", "disclosure", "consent")


# ------------------------------------------------------------------ choices (EMP-02, EMP-03)
def industries():
    return Industry.objects.filter(is_active=True, published_version__isnull=False)


def roles_for(company, industry):
    """Active roles allowed for this industry and the company's plan."""
    plan_key = company.plan.key if company.plan_id else ""
    out = []
    for role in EmployeeRole.objects.filter(is_active=True).prefetch_related("industries"):
        ids = {i.pk for i in role.industries.all()}
        if ids and industry.pk not in ids:
            continue
        if role.plan_keys and plan_key not in role.plan_keys:
            continue
        out.append(role)
    return out


def _version_for(company, industry):
    if company.industry_id == industry.pk and company.template_version_id:
        return company.template_version
    return industry.published_version


# ------------------------------------------------------------------ cleaning
def _texts(value, label):
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{label}: give a text per language.")
    return {k: str(v).strip() for k, v in value.items() if k in LANGUAGE_CODES and str(v or "").strip()}


def _lines(value):
    if isinstance(value, str):
        value = value.splitlines()
    return [str(v).strip() for v in value or [] if str(v).strip()]


def clean_rules(company, rules):
    """EMP-09 rules → stored form."""
    rules = dict(rules or {})
    out = {}
    for key in TEXT_LIST_RULES:
        if key in rules:
            out[key] = _lines(rules[key])
    for key in TRANSLATED_RULES:
        if key in rules:
            out[key] = _texts(rules[key], key.replace("_", " ").capitalize())
    if "after_hours_message" in rules:
        out["after_hours_message"] = str(rules["after_hours_message"] or "").strip()[:500]
    if "fallback_action" in rules:
        if rules["fallback_action"] not in ("callback", "message"):
            raise ValidationError("Fallback action must be callback or message.")
        out["fallback_action"] = rules["fallback_action"]
    if "max_call_minutes" in rules:
        try:
            out["max_call_minutes"] = max(1, min(int(rules["max_call_minutes"] or 0), 120))
        except (TypeError, ValueError):
            raise ValidationError("Maximum call duration must be a number of minutes.") from None
    if "recording" in rules:
        out["recording"] = bool(rules["recording"])
    if "working_hours" in rules:
        from apps.tenancy.profile import clean_business_hours

        out["working_hours"] = clean_business_hours(rules["working_hours"] or {}) if rules["working_hours"] else {}
    if "transfer_user_ids" in rules:
        from apps.crm.services import members

        ids = {str(u.pk) for u in members(company)}
        chosen = [str(i) for i in rules["transfer_user_ids"] or [] if i]
        if set(chosen) - ids:
            raise ValidationError("Transfer targets must be members of your team.")
        out["transfer_user_ids"] = chosen
    if "follow_up" in rules:
        f = rules["follow_up"] or {}
        try:
            out["follow_up"] = {"enabled": bool(f.get("enabled", True)), "after_hours": int(f.get("after_hours") or 24)}
        except (TypeError, ValueError):
            raise ValidationError("Follow-up delay must be a number of hours.") from None
    return out


def _clean(employee, data):
    """Apply and validate the changed settings; returns the list of changed config fields."""
    company = employee.company
    if "industry" in data:
        industry = industries().filter(pk=data["industry"]).first() or industries().filter(key=data["industry"]).first()
        if not industry:
            raise ValidationError("Choose an active industry.")
        if industry.pk != employee.industry_id:
            employee.industry = industry
            employee.template_version = _version_for(company, industry)
            employee.qualification, employee.greetings = [], {}
    if "role" in data:
        role = next(
            (
                r
                for r in roles_for(company, employee.industry)
                if str(r.pk) == str(data["role"]) or r.key == data["role"]
            ),
            None,
        )
        if not role:
            raise ValidationError("This employee type is not available for the industry or your plan.")
        employee.role = role
    if "name" in data:
        employee.name = str(data["name"] or "").strip()[:80]
    if "avatar" in data:
        employee.avatar = str(data["avatar"] or "").strip()[:500]
    if "persona" in data:
        p = data["persona"] or {}
        tone = p.get("tone") or "friendly"
        if tone not in dict(AIEmployee.TONES):
            raise ValidationError("Tone must be friendly or formal.")
        employee.persona = {
            "description": str(p.get("description") or "").strip()[:2000],
            "tone": tone,
            "gender": str(p.get("gender") or "").strip()[:20],
        }
    if "greetings" in data:
        employee.greetings = _texts(data["greetings"], "Greeting")
    if "voices" in data:
        v = data["voices"] or {}
        try:
            speed = float(v.get("speed") or 1.0)
        except (TypeError, ValueError):
            raise ValidationError("Speaking speed must be a number.") from None
        employee.voices = {
            **{k: str(x) for k, x in v.items() if k in LANGUAGE_CODES},
            "speed": max(0.5, min(speed, 2.0)),
        }
    if "languages" in data or "primary_language" in data:
        langs = [c for c in (data.get("languages") or employee.languages or []) if c in LANGUAGE_CODES]
        primary = data.get("primary_language") or employee.primary_language
        supported = employee.industry.supported_languages or LANGUAGE_CODES
        if primary not in LANGUAGE_CODES:
            raise ValidationError("Choose the primary language.")
        langs = list(dict.fromkeys([primary, *langs]))
        if set(langs) - set(supported):
            raise ValidationError(f"{employee.industry.name} supports: {', '.join(supported)}.")
        employee.primary_language, employee.languages = primary, langs
    if "rules" in data:
        employee.rules = {**(employee.rules or {}), **clean_rules(company, data["rules"])}
    if "qualification" in data:
        flow = []
        for q in data["qualification"] or []:
            question = q.get("question")
            if isinstance(question, str):
                question = {employee.primary_language: question}
            question = _texts(question, "Question")
            if question:
                flow.append({"field": str(q.get("field") or "").strip(), "question": question})
        employee.qualification = flow
    if "tools" in data:
        allowed = {t.key for t in toolkit.available(employee)}
        chosen = {str(k): bool(v) for k, v in (data["tools"] or {}).items()}
        if set(chosen) - allowed:
            raise ValidationError(f"Unknown tools: {', '.join(sorted(set(chosen) - allowed))}.")
        employee.tools = chosen
    if "calendar_resources" in data:
        ids = [str(i) for i in data["calendar_resources"] or [] if i]
        if Resource.objects.filter(company=company, pk__in=ids).count() != len(set(ids)):
            raise ValidationError("Unknown calendar resource.")
        employee.calendar_resources = ids
    if "wizard_step" in data:
        employee.wizard_step = max(employee.wizard_step, min(int(data["wizard_step"] or 1), len(WIZARD_STEPS)))
    if not employee.name:
        raise ValidationError("Give the AI Employee a name.")


def snapshot(employee):
    return {f: _plain(getattr(employee, f)) for f in CONFIG_FIELDS}


def _plain(value):
    return str(value) if value is not None and not isinstance(value, (str, int, float, bool, list, dict)) else value


# ------------------------------------------------------------------ create / update (EMP-02 … EMP-12)
def _defaults(company, industry, role):
    version = _version_for(company, industry)
    supported = industry.supported_languages or LANGUAGE_CODES
    primary = company.default_language or setting("locale.default_language")
    primary = primary if primary in supported else supported[0]
    return {
        "industry": industry,
        "role": role,
        "template_version": version,
        "primary_language": primary,
        "languages": list(supported),
        "rules": {
            "fallback_action": "callback",
            "follow_up": {"enabled": True, "after_hours": 24},
            "recording": True,
            **(role.default_rules or {}),
        },
    }


def _check_count(company):
    used = AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED).count()
    limits.check(company, "ai_employees", used, label="AI Employees")


@transaction.atomic
def create_employee(company, data, user=None, request=None):
    _check_count(company)
    industry = industries().filter(Q(pk=_uuid(data.get("industry"))) | Q(key=data.get("industry") or "")).first()
    industry = industry or (company.industry if company.industry and company.industry.is_active else None)
    if not industry:
        raise ValidationError("Choose an active industry.")
    roles = roles_for(company, industry)
    role = next((r for r in roles if str(r.pk) == str(data.get("role")) or r.key == data.get("role")), None)
    role = role or (roles[0] if roles and not data.get("role") else None)
    if not role:
        raise ValidationError("This employee type is not available for the industry or your plan.")
    employee = AIEmployee(
        company=company,
        name=str(data.get("name") or setting("ai.default_employee_name")).strip()[:80],
        created_by=user if user and user.is_authenticated else None,
        **_defaults(company, industry, role),
    )
    _clean(employee, {k: v for k, v in data.items() if k not in ("industry", "role")})
    employee.save()
    ConfigVersion.objects.create(
        company=company,
        employee=employee,
        version=1,
        snapshot=snapshot(employee),
        changes=["created"],
        changed_by=employee.created_by,
        changed_by_email=getattr(user, "email", "") or "",
    )
    record(request, "ai_employee.create", "ai_employee", employee.id, company=company)
    return employee


@transaction.atomic
def update_employee(employee, data, user=None, request=None):
    """Any wizard step, any time (EMP-12). A real change becomes a new configuration version."""
    if employee.status == AIEmployee.ARCHIVED:
        raise ValidationError("Archived AI Employees cannot be edited.")
    before = snapshot(employee)
    _clean(employee, data)
    after = snapshot(employee)
    changed = [k.removesuffix("_id") for k in CONFIG_FIELDS if before[k] != after[k]]
    if changed:
        employee.config_version += 1
        ConfigVersion.objects.create(
            company=employee.company,
            employee=employee,
            version=employee.config_version,
            snapshot=after,
            changes=changed,
            changed_by=user if user and user.is_authenticated else None,
            changed_by_email=getattr(user, "email", "") or "",
        )
        record(
            request,
            "ai_employee.update",
            "ai_employee",
            employee.id,
            company=employee.company,
            changes={"fields": changed, "version": employee.config_version},
        )
    employee.save()
    return employee


# ------------------------------------------------------------------ test, readiness, activation (EMP-10, EMP-11)
def mark_tested(employee, user=None, request=None):
    """The current configuration passed a test in the console (at least one AI answer to a customer message)."""
    tested = (
        Conversation.objects.filter(employee=employee, is_test=True, employee_version=employee.config_version)
        .filter(messages__role="customer")
        .exists()
    )
    if not tested:
        raise ValidationError("Have a test conversation with this version first.")
    employee.tested_version = employee.config_version
    employee.save(update_fields=["tested_version", "updated_at"])
    record(
        request,
        "ai_employee.tested",
        "ai_employee",
        employee.id,
        company=employee.company,
        changes={"version": employee.config_version},
    )
    return employee


def readiness(employee):
    """EMP-11 checklist. Channels arrive in Phase 5 (phone) and 6 (WhatsApp, website chat)."""
    from apps.knowledge.services import usable_chunks

    company = employee.company
    used = AIEmployee.objects.filter(company=company, status=AIEmployee.ACTIVE).exclude(pk=employee.pk).count()
    cap = limits.limit(company, "ai_employees")
    return [
        {
            "key": "template",
            "label": "Industry template published",
            "ok": bool(employee.template_version_id),
            "required": True,
        },
        {
            "key": "knowledge",
            "label": "Approved knowledge available to this employee",
            "ok": usable_chunks(company, employee).exists(),
            "required": True,
        },
        {
            "key": "test",
            "label": f"Test passed for the current settings (version {employee.config_version})",
            "ok": employee.test_passed,
            "required": True,
        },
        {
            "key": "plan",
            "label": "Within your plan's AI Employee limit" + (f" ({used} of {cap} active)" if cap is not None else ""),
            "ok": cap is None or used < cap,
            "required": True,
        },
        {
            "key": "channel",
            "label": "Channel connected (phone, WhatsApp or website chat)",
            "ok": False,
            "required": False,
            "help": "Phone numbers arrive in Phase 5, WhatsApp and the website chat widget in Phase 6.",
        },
    ]


def activate(employee, user=None, request=None):
    if employee.paused_by_platform:
        raise ValidationError("Paused by the platform team: contact support.")
    missing = [c["label"] for c in readiness(employee) if c["required"] and not c["ok"]]
    if missing:
        raise ValidationError(["Not ready: " + m for m in missing])
    employee.status, employee.activated_at, employee.paused_reason = AIEmployee.ACTIVE, timezone.now(), ""
    employee.save(update_fields=["status", "activated_at", "paused_reason", "updated_at"])
    record(request, "ai_employee.activate", "ai_employee", employee.id, company=employee.company)
    return employee


def pause(employee, reason="", by_platform=False, user=None, request=None):
    if employee.status == AIEmployee.ARCHIVED:
        raise ValidationError("Archived AI Employees cannot be paused.")
    employee.status, employee.paused_reason = AIEmployee.PAUSED, str(reason or "")[:255]
    employee.paused_by_platform = employee.paused_by_platform or by_platform
    employee.save(update_fields=["status", "paused_reason", "paused_by_platform", "updated_at"])
    record(
        request,
        "ai_employee.pause",
        "ai_employee",
        employee.id,
        company=employee.company,
        category="security" if by_platform else "general",
        changes={"reason": reason, "platform": by_platform},
    )
    return employee


def release_platform_pause(employee, request=None):
    employee.paused_by_platform = False
    employee.save(update_fields=["paused_by_platform", "updated_at"])
    record(
        request,
        "ai_employee.platform_release",
        "ai_employee",
        employee.id,
        company=employee.company,
        category="security",
    )
    return employee


def archive(employee, user=None, request=None):
    employee.status = AIEmployee.ARCHIVED
    employee.save(update_fields=["status", "updated_at"])
    record(request, "ai_employee.archive", "ai_employee", employee.id, company=employee.company)
    return employee


def restore_version(employee, version, user=None, request=None):
    """Bring back an earlier configuration (saved as a new version)."""
    snap = ConfigVersion.objects.get(employee=employee, version=version).snapshot
    data = {k.removesuffix("_id"): v for k, v in snap.items() if k not in ("industry_id", "template_version_id")}
    data.pop("role", None)
    employee.role_id = snap.get("role_id") or employee.role_id
    return update_employee(employee, data, user, request)


# ------------------------------------------------------------------ EMP-14 ready-made employee on approval
def create_from_template(company, user=None, request=None, force=False):
    """A draft AI Employee from the company's industry template (role, script, questions, greetings, languages),
    plus the template FAQs as a draft FAQ list. Idempotent unless `force` (Super Admin "create another")."""
    from apps.knowledge.services import add_template_faqs

    with company_context(company.id):
        if not force and AIEmployee.objects.filter(company=company).exists():
            return None
        industry = company.industry
        if not industry or not industry.published_version_id:
            return None
        roles = roles_for(company, industry)
        if not roles:
            return None
        employee = create_employee(company, {"industry": str(industry.pk), "role": str(roles[0].pk)}, user, request)
        add_template_faqs(company, employee.template_version, user)
        return employee


def change_role(employee, role_key, user=None, request=None):
    """Super Admin one-click role change for a company's employee (EMP-14)."""
    return update_employee(employee, {"role": role_key}, user, request)


# ------------------------------------------------------------------ list / stats (EMP-01, SA-08)
def stats(employees):
    """{employee id: {"conversations", "calls", "leads", "appointments"}}."""
    from apps.crm.models import Lead

    ids = [e.pk for e in employees]
    conv = dict(
        Conversation.objects.filter(employee_id__in=ids, is_test=False)
        .values("employee_id")
        .annotate(n=Count("id"))
        .values_list("employee_id", "n")
    )
    calls = dict(
        Conversation.objects.filter(employee_id__in=ids, channel="voice")
        .values("employee_id")
        .annotate(n=Count("id"))
        .values_list("employee_id", "n")
    )
    leads = dict(
        Lead.objects.filter(assigned_ai_employee_id__in=ids, deleted_at__isnull=True)
        .values("assigned_ai_employee_id")
        .annotate(n=Count("id"))
        .values_list("assigned_ai_employee_id", "n")
    )
    appts = dict(
        Appointment.objects.filter(created_by_type="ai", lead__assigned_ai_employee_id__in=ids)
        .values("lead__assigned_ai_employee_id")
        .annotate(n=Count("id"))
        .values_list("lead__assigned_ai_employee_id", "n")
    )
    return {
        e.pk: {
            "conversations": conv.get(e.pk, 0),
            "calls": calls.get(e.pk, 0),
            "leads": leads.get(e.pk, 0),
            "appointments": appts.get(e.pk, 0),
        }
        for e in employees
    }


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
