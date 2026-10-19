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
