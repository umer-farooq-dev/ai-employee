"""Company profile and settings (AUTH-09, CP-06 first part) and the onboarding checklist (AUTH-10)."""

import datetime
import re

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.services import record

from .context import platform_context
from .models import Company, Invitation, Membership

PROFILE_FIELDS = [
    "name",
    "legal_name",
    "logo",
    "email",
    "phone",
    "website",
    "gstin",
    "address",
    "city",
    "state",
    "timezone",
    "default_language",
]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def update_profile(company, data: dict, request=None):
    changed = [f for f in PROFILE_FIELDS if f in data and getattr(company, f) != data[f]]
    for field in changed:
        setattr(company, field, data[field])
    if changed:
        company.save(update_fields=changed + ["updated_at"])
        record(request, "company.profile_update", "company", company.id, company=company, changes={"fields": changed})
    return company


def clean_business_hours(hours: dict) -> dict:
    """{mon: {open: "09:00", close: "18:00", closed: false}, …} for all seven days."""
    cleaned = {}
    for day in Company.WEEKDAYS:
        row = (hours or {}).get(day) or {}
        closed = bool(row.get("closed"))
        opens, closes = str(row.get("open") or ""), str(row.get("close") or "")
        if not closed:
            if not (TIME_RE.match(opens) and TIME_RE.match(closes)):
                raise ValidationError(f"{day.title()}: enter opening and closing time as HH:MM, or mark it closed.")
            if opens >= closes:
                raise ValidationError(f"{day.title()}: closing time must be after opening time.")
        cleaned[day] = {"open": "" if closed else opens, "close": "" if closed else closes, "closed": closed}
    return cleaned


def clean_holidays(holidays: list) -> list:
    cleaned, seen = [], set()
    for row in holidays or []:
        date, name = str(row.get("date") or "").strip(), str(row.get("name") or "").strip()
        if not date and not name:
            continue
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ValidationError(f"Holiday {name or date!r}: enter the date as YYYY-MM-DD.") from None
        if date in seen:
            raise ValidationError(f"{date} is listed twice.")
        seen.add(date)
        cleaned.append({"date": date, "name": name[:100]})
    return sorted(cleaned, key=lambda r: r["date"])


def set_hours(company, business_hours=None, holidays=None, request=None):
    fields = []
    if business_hours is not None:
        company.business_hours = clean_business_hours(business_hours)
        fields.append("business_hours")
    if holidays is not None:
        company.holidays = clean_holidays(holidays)
        fields.append("holidays")
    if fields:
        company.save(update_fields=fields + ["updated_at"])
        record(request, "company.hours_update", "company", company.id, company=company, changes={"fields": fields})
    return company


# ------------------------------------------------------------------ onboarding (AUTH-10)
# Every step is worked out from the company's own data, so it ticks itself the moment the feature is used.
STEPS = [
    ("profile", "Complete your company profile and business hours", "panel:company_settings"),
    ("team", "Invite your team (optional)", "panel:team"),
    ("ai_employee", "Your AI Employee is ready", "panel:ai_list"),
    ("knowledge", "Add your business knowledge", "panel:kb"),
    ("catalogue", "Add your properties, packages or courses", "panel:catalog_home"),
    ("channel", "Connect your phone, WhatsApp or website chat", "panel:calling_settings"),
    ("test", "Test your AI Employee", "panel:ai_list"),
    ("activate", "Activate your AI Employee", "panel:ai_list"),
]


def _auto_done(company, key):
    from apps.agents.models import AIEmployee
    from apps.catalog.models import CatalogItem
    from apps.knowledge.models import FAQ, Source
    from apps.voice.models import PhoneNumber

    employees = AIEmployee.all_companies.filter(company=company).exclude(status=AIEmployee.ARCHIVED)
    with platform_context():
        if key == "profile":
            return bool(company.address and company.email and company.phone and company.business_hours)
        if key == "team":
            return (
                Membership.all_companies.filter(company=company).count() > 1
                or Invitation.all_companies.filter(company=company).exists()
            )
        if key == "ai_employee":
            return employees.exists()
        if key == "knowledge":
            return (
                Source.all_companies.filter(company=company, approval=Source.APPROVED).exists()
                or FAQ.all_companies.filter(company=company, approval=Source.APPROVED).exists()
            )
        if key == "catalogue":
            return CatalogItem.all_companies.filter(company=company).exists()
        if key == "channel":  # a connected phone / WhatsApp number or a website chat on the company's site
            from apps.webchat.models import ChatWidget
            from apps.whatsapp.models import WhatsAppNumber

            return (
                PhoneNumber.objects.filter(company=company, employee__isnull=False, status="active").exists()
                or WhatsAppNumber.objects.filter(company=company, employee__isnull=False, status="active").exists()
                or ChatWidget.all_companies.filter(company=company, is_enabled=True)
                .exclude(allowed_domains=[])
                .exists()
            )
        if key == "test":
            return any(e.test_passed for e in employees)
        if key == "activate":
            return employees.filter(status=AIEmployee.ACTIVE).exists()
    return False


def onboarding(company) -> dict:
    steps = []
    for key, label, url_name in STEPS:
        done = key in company.onboarding or _auto_done(company, key)
        steps.append({"key": key, "label": label, "url_name": url_name, "done": done, "available": bool(url_name)})
    completed = sum(s["done"] for s in steps)
    return {"steps": steps, "completed": completed, "total": len(steps), "percent": round(100 * completed / len(steps))}


def mark_done(company, key, request=None):
    """Called by later phases when a step is completed (e.g. the first knowledge source is approved)."""
    if key not in dict((k, v) for k, v, _ in STEPS) or key in company.onboarding:
        return
    company.onboarding = {**company.onboarding, key: timezone.now().isoformat()}
    company.save(update_fields=["onboarding", "updated_at"])
    record(request, "company.onboarding_step", "company", company.id, company=company, changes={"step": key})
