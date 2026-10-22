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
    if key == "calls":
        return Call.objects.filter(company=company, queued_at__gte=since).exclude(status=Call.CANCELED).count()
    if key == "voice_minutes":  # billed per started minute of each call (the metered usage)
        return round(
            UsageEvent.objects.filter(
                company=company, meter__in=("voice_minutes_inbound", "voice_minutes_outbound"), occurred_at__gte=since
            ).aggregate(s=Sum("quantity"))["s"]
            or 0
        )
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


def current(company, key, now=None):
    """What counts against each limit right now (monthly meters for this month; the rest as of now)."""
    if key in MONTHLY:
        return used(company, key, now)
    from apps.agents.models import AIEmployee

    if key == "ai_employees":
        return AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED).count()
    if key == "users":
        from apps.tenancy.team import seats_used

        return seats_used(company)
    if key in ("kb_storage_mb", "kb_sources"):
        from apps.knowledge.models import Source

        sources = Source.objects.filter(company=company)
        if key == "kb_sources":
            return sources.count()
        return round((sources.aggregate(s=Sum("file_size"))["s"] or 0) / 1024 / 1024, 1)
    if key == "concurrent_calls":
        from apps.voice.services import live_calls

        return live_calls(company)
    if key == "campaigns":
        from apps.campaigns.models import Campaign

        return Campaign.objects.filter(company=company, status__in=Campaign.ACTIVE).count()
    if key == "custom_fields":
        from apps.industries.models import FieldDefinition

        return FieldDefinition.objects.filter(company=company).count()
    raise KeyError(key)


def overview(company, now=None):
    """USE-02 / USE-03: every limit with its use, what is left, and the overage so far for soft limits."""
    rows = []
    for key, label in ENTITLEMENTS:
        e = limits.entitlement(company, key)
        count = current(company, key, now)
        cap = e["limit"]
        over = max(count - cap, 0) if cap is not None else 0
        rows.append(
            {
                "key": key,
                "label": label,
                "monthly": key in MONTHLY,
                "used": count,
                "limit": cap,
                "left": None if cap is None else max(cap - count, 0),
                "percent": min(round(count * 100 / cap), 100) if cap else (100 if cap == 0 and count else 0),
                "enforcement": e["enforcement"],
                "over": over,
                "overage_paise": over * (e["overage"] or 0) if e["enforcement"] == "soft" else 0,
            }
        )
    return rows


def meters(company, now=None):
    """USE-01 detail for the Billing page: voice minutes in / out, calls, WhatsApp, AI, speech, this month."""
    from apps.agents.models import UsageEvent

    since = month_start(company, now)
    sums = dict(
        UsageEvent.objects.filter(company=company, occurred_at__gte=since)
        .values_list("meter")
        .annotate(s=Sum("quantity"))
        .values_list("meter", "s")
    )
    return [
        ("Voice minutes (inbound)", round(sums.get("voice_minutes_inbound") or 0)),
        ("Voice minutes (outbound)", round(sums.get("voice_minutes_outbound") or 0)),
        ("Calls", round(sums.get("calls") or 0)),
        ("WhatsApp messages (billed by Meta)", round(sums.get("whatsapp_messages") or 0)),
        ("AI credits", round(sums.get("ai_credits") or 0, 1)),
        ("AI tokens", round((sums.get("ai_input_tokens") or 0) + (sums.get("ai_output_tokens") or 0))),
        ("Speech-to-text (minutes)", round((sums.get("stt_seconds") or 0) / 60, 1)),
        ("Text-to-speech (characters)", round(sums.get("tts_characters") or 0)),
    ]


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
                    reverse("panel:billing"),
                    email=(
                        "alerts/usage",
                        {"limit_label": label, "used": count, "cap": cap, "percent": percent},
                    ),
                    data=tag,
                )
                sent += 1
    return sent
