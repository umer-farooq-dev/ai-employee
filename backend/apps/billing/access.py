"""What a company may use right now: plan feature flags with company overrides (SA-20, SUB-05), the billing hold
(SUB-03: unpaid → the AI stops) and the monthly AI credits (USE-03 / USE-04). One place every channel asks."""

from .models import FEATURES

LABELS = dict(FEATURES)

# Permission → the feature it belongs to. A switched-off feature removes the permission (menu, screens, API).
PERM_FEATURES = {
    "calls.": "voice_calls",
    "phone_numbers.": "voice_calls",
    "recordings.": "recordings",
    "whatsapp.": "whatsapp",
    "campaigns.": "campaigns",
    "calendar.": "calendar",
    "knowledge.": "knowledge",
    "catalog.": "catalog",
    "leads.import": "lead_import",
    "leads.export": "lead_import",
    "analytics.": "analytics",
}
CHANNEL_FEATURES = {"voice": "voice_calls", "whatsapp": "whatsapp", "web_chat": "web_chat"}


def features(company):
    """{feature: on/off} for the company (cached on the object for the request)."""
    cached = getattr(company, "_features", None)
    if cached is not None:
        return cached
    from apps.tenancy.context import platform_context

    from .models import Plan, Subscription

    flags = {}
    if company.plan_id:
        flags = Plan.objects.filter(pk=company.plan_id).values_list("flags", flat=True).first() or {}
    with platform_context():  # permission checks also run outside a company context (filtered by company here)
        sub = (
            Subscription.all_companies.filter(company_id=company.pk).values_list("feature_overrides", flat=True).first()
            or {}
        )
    out = {key: bool(sub.get(key, flags.get(key, True))) for key, _ in FEATURES}
    company._features = out
    return out


def enabled(company, key):
    return features(company).get(key, True)


def perm_allowed(company, perm):
    for prefix, feature in PERM_FEATURES.items():
        if perm.startswith(prefix):
            return enabled(company, feature)
    return True


def blocked(company, feature=None):
    """The reason the AI may not work for the company now ("" = it may)."""
    if company.billing_hold:
        return "The subscription is unpaid, so the AI Employees are paused. Pay in Billing to continue."
    if feature and not enabled(company, feature):
        return f"{LABELS[feature].split(' (')[0]} is not included in your plan."
    return ""


def credits_left(company):
    """AI credits left this month under a hard limit; None = no hard limit."""
    from . import limits
    from .usage import used

    cap = limits.hard_cap(company, "ai_credits")
    return None if cap is None else cap - used(company, "ai_credits")
