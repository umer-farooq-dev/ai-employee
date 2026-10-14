from django import template

from apps.panel import menu

register = template.Library()


@register.simple_tag(takes_context=True)
def company_menu(context):
    """{% company_menu as items %} — sidebar items for the signed-in user's role and plan (CP-02)."""
    request = context["request"]
    return menu.items(request.user, getattr(request, "company", None))
