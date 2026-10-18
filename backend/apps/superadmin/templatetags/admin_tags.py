from django import template

from apps.core.money import format_inr, format_inr_short
from apps.platform_config import services as config
from apps.rbac.services import has_perm

register = template.Library()


@register.filter
def can(user, key):
    """{% if request.user|can:"companies.view" %} — menus and buttons follow the user's permissions."""
    return has_perm(user, key, None)


@register.filter
def local_iso(value):
    """ISO timestamp string (stored in JSON, UTC) → aware datetime in the current timezone, for |date."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(str(value or ""))
    return timezone.localtime(parsed) if parsed else None


@register.filter
def routes(described):
    """'["sarvam/saarika", "deepgram/nova-3"]' (call metrics) → 'sarvam/saarika → deepgram/nova-3'."""
    import json

    try:
        return " → ".join(json.loads(described))
    except (TypeError, ValueError):
        return described or ""


@register.filter
def get(mapping, key):
    return (mapping or {}).get(key)


@register.filter
def inr(paise):
    """Paise → '₹2,999' using the platform number format setting (SA-25)."""
    return format_inr(paise, indian=config.get("locale.number_format") == "indian")


@register.filter
def inr_short(paise):
    """Paise → '₹70 Lakh' / '₹1.2 Cr' (CAT-08)."""
    return format_inr_short(paise)


@register.filter
def bs(field):
    """Render a bound form field with the Bootstrap class that fits its widget (used by allauth pages)."""
    widget = field.field.widget
    if getattr(widget, "input_type", "") in ("checkbox", "radio"):
        css = "form-check-input"
    elif widget.__class__.__name__.endswith("Select"):
        css = "form-select"
    else:
        css = "form-control"
    if field.errors:
        css += " is-invalid"
    return field.as_widget(attrs={"class": css})


@register.filter
def person(user):
    """User → full name, else email, else '' (safe for empty assignees)."""
    return (user.full_name or user.email) if user else ""


@register.filter
def signed(file_key):
    """Private file key → short-lived signed link (TEN-03)."""
    from apps.core.storage import signed_url

    return signed_url(file_key) if file_key else ""
