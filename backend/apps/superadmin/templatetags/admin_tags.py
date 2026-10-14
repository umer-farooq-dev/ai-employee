from django import template

from apps.platform_config import services as config
from apps.rbac.services import has_perm

register = template.Library()


@register.filter
def can(user, key):
    """{% if request.user|can:"companies.view" %} — menus and buttons follow the user's permissions."""
    return has_perm(user, key, None)


@register.filter
def get(mapping, key):
    return (mapping or {}).get(key)


def _indian_group(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


@register.filter
def inr(paise):
    """Paise → '₹2,999' using the platform number format setting (SA-25)."""
    if paise in (None, ""):
        return "—"
    rupees, rem = divmod(int(paise), 100)
    whole = _indian_group(rupees) if config.get("locale.number_format") == "indian" else f"{rupees:,}"
    return f"₹{whole}" + (f".{rem:02d}" if rem else "")


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
