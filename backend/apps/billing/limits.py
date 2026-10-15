"""Plan limits (SUB-02 entitlements) read by the features that enforce them."""

from django.core.exceptions import ValidationError

from .models import PlanEntitlement


def limit(company, key):
    """The company's plan limit for `key`; None = not limited."""
    row = PlanEntitlement.objects.filter(plan_id=company.plan_id, key=key).first()
    return row.limit_value if row else None


def check(company, key, used, adding=1, label=""):
    """Raise when `used + adding` would pass a hard plan limit."""
    cap = limit(company, key)
    if cap is not None and used + adding > cap:
        raise ValidationError(f"Your plan allows {cap} {label or key.replace('_', ' ')}. Upgrade to add more.")
