from django import template

from apps.panel import menu

register = template.Library()


@register.simple_tag(takes_context=True)
def company_can(context, key):
    """{% company_can "handoffs.receive" as allowed %} — a company permission of the signed-in user."""
    from apps.rbac.services import has_perm

    request = context["request"]
    company = getattr(request, "company", None)
    return bool(company and has_perm(request.user, key, company))


@register.simple_tag(takes_context=True)
def company_menu(context):
    """{% company_menu as items %} — sidebar items for the signed-in user's role and plan (CP-02)."""
    request = context["request"]
    return menu.items(request.user, getattr(request, "company", None))


@register.simple_tag
def setting(key):
    """A System Settings value in a template, e.g. {% setting "notifications.poll_seconds" %}."""
    from apps.platform_config.services import get

    return get(key)


@register.filter
def money(minor, code=""):
    """Minor units → "₹1,23,456.00" / "$1,234.50" (Billing). money:"USD" names the currency (default: the base
    currency); money:False drops the decimals in the base currency."""
    from apps.billing.services import fmt

    if minor is None:
        return "—"
    return fmt(minor, decimals=False) if code is False else fmt(minor, code or "")


@register.filter
def money_short(minor, code=""):
    """Like money, without decimals: "$49", "₹2,999"."""
    from apps.billing.services import fmt

    return "—" if minor is None else fmt(minor, code or "", decimals=False)


@register.filter
def convert(minor, code=""):
    """A base-currency amount in another currency at today's rate (unrounded)."""
    from apps.billing.currency import convert as to

    return None if minor is None else to(minor, code, rounded=False) if code else minor


@register.filter
def rupees(minor, code=""):
    """Minor units → "1234.50" for form inputs (empty for None); rupees:"JPY" for another currency."""
    from apps.billing.currency import base, exponent, to_major

    if minor in (None, ""):
        return ""
    code = code or base()
    text = f"{to_major(minor, code):.{exponent(code)}f}"
    return text.rstrip("0").rstrip(".") if "." in text and set(text.split(".")[1]) == {"0"} else text


def _viewer_currency(context):
    from apps.billing.currency import base
    from apps.billing.region import visitor_currency

    request = context.get("request")
    return visitor_currency(request) if request else base()


@register.simple_tag(takes_context=True)
def local_money(context, minor, decimals=False):
    """Platform figures (kept in the base currency) in the viewer's own currency: Rs in Pakistan, $ in the USA."""
    from apps.billing.currency import base, convert, fmt

    code = _viewer_currency(context)
    value = convert(minor or 0, code, rounded=False)
    if value is None:  # no rate for it yet
        code, value = base(), minor or 0
    return fmt(value, code, decimals=bool(decimals))


@register.simple_tag(takes_context=True)
def local_currency(context):
    """{code, rate per 1 base unit, digits} for charts that format amounts in the browser."""
    from apps.billing.currency import base, exponent, rate

    code = _viewer_currency(context)
    r = rate(code)
    if r is None:
        code, r = base(), 1
    return {"code": code, "rate": float(r), "base_digits": exponent(base())}
