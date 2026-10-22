"""Plan limits (SUB-02 entitlements, SUB-04 company overrides, USE-03 hard stop or overage, USE-04 extra credits)
read by the features that enforce them."""

from django.core.exceptions import ValidationError

from .models import PlanEntitlement


def entitlement(company, key):
    """→ {"limit": n | None (unlimited), "enforcement": "hard" | "soft", "overage": paise | None}.
    A company override set by Super Admin (enterprise) wins over the plan; AI credits add this month's adjustments."""
    from .models import Subscription

    sub = Subscription.objects.filter(company=company).only("custom_limits").first()
    custom = (sub.custom_limits if sub else {}).get(key)
    if custom:
        out = {
            "limit": custom.get("limit"),
            "enforcement": custom.get("enforcement") or PlanEntitlement.HARD,
            "overage": custom.get("overage"),
        }
    else:
        row = PlanEntitlement.objects.filter(plan_id=company.plan_id, key=key).first()
        out = {
            "limit": row.limit_value if row else None,
            "enforcement": row.enforcement if row else PlanEntitlement.HARD,
            "overage": row.overage_price_paise if row else None,
        }
    if key == "ai_credits" and out["limit"] is not None:
        out["limit"] += extra_credits(company)
    return out


def extra_credits(company, now=None):
    """USE-04: credits given (or taken back) by Super Admin for this month."""
    from django.db.models import Sum

    from .models import CreditAdjustment
    from .usage import month_start

    month = month_start(company, now).date()
    return CreditAdjustment.objects.filter(company=company, month=month).aggregate(s=Sum("credits"))["s"] or 0


def limit(company, key):
    """The company's limit for `key`; None = not limited."""
    return entitlement(company, key)["limit"]


def hard_cap(company, key):
    """The limit when it stops the feature; None when unlimited or overage is allowed (soft)."""
    e = entitlement(company, key)
    return e["limit"] if e["enforcement"] == PlanEntitlement.HARD else None


def check(company, key, used, adding=1, label=""):
    """Raise when `used + adding` would pass a hard limit (a soft limit lets usage continue as overage)."""
    cap = hard_cap(company, key)
    if cap is not None and used + adding > cap:
        raise ValidationError(f"Your plan allows {cap} {label or key.replace('_', ' ')}. Upgrade to add more.")
