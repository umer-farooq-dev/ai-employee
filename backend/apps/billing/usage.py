"""CP-03 usage alerts: this month's use of the monthly plan limits, and an alert to the people who see billing when
it passes the levels in System Settings → Team alerts (once a month per limit and level)."""

from django.db.models import Sum
from django.utils import timezone

from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context, platform_context

from . import limits
from .models import ENTITLEMENTS

MONTHLY = ("voice_minutes", "calls", "whatsapp_conversations", "ai_credits")


def month_start(company, now=None):
    from apps.agents.tools import company_tz

    local = timezone.localtime(now or timezone.now(), company_tz(company))
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def used(company, key, now=None):
    """The same counts the limits are enforced on."""
    from apps.agents.models import Conversation, UsageEvent
    from apps.voice.models import Call

    since = month_start(company, now)
    if key in ("calls", "voice_minutes"):
        calls = Call.objects.filter(company=company, queued_at__gte=since).exclude(status=Call.CANCELED)
        if key == "calls":
            return calls.count()
        return round((calls.aggregate(s=Sum("duration_sec"))["s"] or 0) / 60)
    if key == "whatsapp_conversations":
        return Conversation.objects.filter(
            company=company, channel="whatsapp", is_test=False, started_at__gte=since
        ).count()
    if key == "ai_credits":
        return round(
            UsageEvent.objects.filter(company=company, meter="ai_credits", occurred_at__gte=since).aggregate(
                s=Sum("quantity")
            )["s"]
            or 0
        )
    raise KeyError(key)


def send_usage_alerts(now=None):
    from django.urls import reverse

    from apps.notifications import alerts
    from apps.notifications.models import Notification
    from apps.tenancy.models import Company

    levels = sorted(int(x) for x in setting("notifications.usage_alert_percent") or [])
    labels, sent = dict(ENTITLEMENTS), 0
    with platform_context():
        companies = list(Company.objects.filter(status__in=(Company.ACTIVE, Company.TRIAL), deleted_at__isnull=True))
    for company in companies:
        with company_context(company.id):
            month = month_start(company, now).strftime("%Y-%m")
            for key in MONTHLY:
                cap = limits.limit(company, key)
                if not cap:
                    continue
                count = used(company, key, now)
                percent = int(count * 100 / cap)
                reached = [lv for lv in levels if percent >= lv]
                if not reached:
                    continue
                level = reached[-1]
                tag = {"meter": key, "month": month, "level": level}
                if Notification.objects.filter(company=company, kind="usage", data__contains=tag).exists():
                    continue
                label = labels[key].split(" / ")[0].lower()
                alerts.notify(
                    company,
                    alerts.people_with(company, "billing.view"),
                    "usage",
                    f"{percent}% of your {label} used this month",
                    f"{count} of {cap} {label}.",
                    reverse("panel:company_home"),
                    email=(
                        "alerts/usage",
                        {"limit_label": label, "used": count, "cap": cap, "percent": percent},
                    ),
                    data=tag,
                )
                sent += 1
    return sent
