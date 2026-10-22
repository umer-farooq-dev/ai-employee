"""Super Admin figures across companies (SA-02 platform dashboard, SA-13 billing, SA-14 usage, USE-06 margin).
Run inside platform_context() (the Super Admin area). Revenue is invoiced value before GST."""

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Invoice, Payment, Subscription

S = Subscription


def month_bounds(month=None):
    """'2026-10' → (start, end) as aware datetimes in the platform timezone; default this month."""
    today = timezone.localdate()
    try:
        first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    except ValueError:
        first = today.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    tz = timezone.get_current_timezone()
    return datetime.combine(first, time.min, tzinfo=tz), datetime.combine(nxt, time.min, tzinfo=tz)


def mrr():
    """Monthly recurring revenue: paying subscriptions at their monthly-equivalent price (before GST)."""
    from . import services

    total = 0
    for sub in S.all_companies.filter(status__in=(S.ACTIVE, S.PAST_DUE)).select_related("company__plan"):
        company = sub.company
        if not company.plan_id or company.deleted_at or not sub.current_period_end:
            continue
        price = services.price(company, company.plan, sub.interval)
        if price:
            value = services.taxable(price, company.plan)
            total += value / 12 if sub.interval == "yearly" else value
    return round(total)


def revenue_by_month(months=6):
    start, _ = month_bounds()
    first = start
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    rows = (
        Invoice.all_companies.filter(status=Invoice.PAID, paid_at__gte=first)
        .annotate(m=TruncMonth("paid_at"))
        .values("m")
        .annotate(v=Sum("subtotal_paise"))
    )
    by = {timezone.localtime(r["m"]).strftime("%Y-%m") if r["m"] else "": r["v"] for r in rows}
    out, cursor = [], timezone.localtime(first).date()
    for _ in range(months):
        key = cursor.strftime("%Y-%m")
        out.append({"month": cursor.strftime("%b %Y"), "key": key, "revenue": by.get(key, 0) or 0})
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def dashboard():
    """SA-02."""
    from apps.agents.models import AIEmployee, UsageEvent
    from apps.audit.models import ErrorLog
    from apps.providers.models import Provider
    from apps.tenancy.models import Company
    from apps.voice.models import Call
    from apps.website.models import Enquiry

    now = timezone.now()
    start, end = month_bounds()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    live = Company.objects.filter(deleted_at__isnull=True)
    companies = live.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status=Company.ACTIVE)),
        trial=Count("pk", filter=Q(status=Company.TRIAL)),
        pending=Count("pk", filter=Q(status=Company.PENDING)),
        suspended=Count("pk", filter=Q(status=Company.SUSPENDED)),
        on_hold=Count("pk", filter=Q(billing_hold__isnull=False)),
        trials_ending=Count(
            "pk", filter=Q(status=Company.TRIAL, trial_ends_at__gte=now, trial_ends_at__lt=now + timedelta(days=7))
        ),
        new_month=Count("pk", filter=Q(created_at__gte=start)),
    )
    usage = dict(
        UsageEvent.all_companies.filter(occurred_at__gte=start, occurred_at__lt=end)
        .values_list("meter")
        .annotate(s=Sum("quantity"))
        .values_list("meter", "s")
    )
    cost = UsageEvent.all_companies.filter(occurred_at__gte=start, occurred_at__lt=end).aggregate(
        s=Sum("provider_cost_paise")
    )["s"]
    revenue = Invoice.all_companies.filter(status=Invoice.PAID, paid_at__gte=start, paid_at__lt=end).aggregate(
        s=Sum("subtotal_paise")
    )["s"]
    providers = [p for p in Provider.objects.filter(is_active=True).order_by("name") if p.health]
    return {
        "companies": companies,
        "ai_employees": AIEmployee.all_companies.filter(status=AIEmployee.ACTIVE).count(),
        "calls_today": Call.all_companies.filter(queued_at__gte=today).exclude(reason__in=Call.TEST_REASONS).count(),
        "minutes_month": round((usage.get("voice_minutes_inbound") or 0) + (usage.get("voice_minutes_outbound") or 0)),
        "ai_credits_month": round(usage.get("ai_credits") or 0),
        "wa_messages_month": round(usage.get("whatsapp_messages") or 0),
        "mrr": mrr(),
        "revenue_month": revenue or 0,
        "cost_month": round(cost or 0),
        "past_due": S.all_companies.filter(status=S.PAST_DUE).count(),
        "failed_payments_month": Payment.all_companies.filter(status=Payment.FAILED, created_at__gte=start).count(),
        "due_invoices": Invoice.all_companies.filter(status=Invoice.DUE).count(),
        "errors_24h": ErrorLog.objects.filter(created_at__gte=now - timedelta(hours=24)).count(),
        "new_enquiries": Enquiry.objects.filter(status=Enquiry.NEW).count(),
        "providers": providers,
        "providers_down": [p for p in providers if not p.health.get("ok")],
        "revenue_series": revenue_by_month(),
    }


def usage_report(month=None):
    """SA-14 / USE-06: per company and per provider for one month — usage, provider cost, revenue, margin."""
    from apps.agents.models import UsageEvent
    from apps.tenancy.models import Company

    start, end = month_bounds(month)
    events = UsageEvent.all_companies.filter(occurred_at__gte=start, occurred_at__lt=end)
    per = {}
    for r in events.values("company_id", "meter").annotate(q=Sum("quantity"), c=Sum("provider_cost_paise")):
        row = per.setdefault(r["company_id"], {"meters": {}, "cost": 0})
        row["meters"][r["meter"]] = r["q"] or 0
        row["cost"] += r["c"] or 0
    revenue = dict(
        Invoice.all_companies.filter(status=Invoice.PAID, paid_at__gte=start, paid_at__lt=end)
        .values_list("company_id")
        .annotate(s=Sum("subtotal_paise"))
        .values_list("company_id", "s")
    )
    names = dict(Company.objects.filter(pk__in=set(per) | set(revenue)).values_list("pk", "name"))
    companies = []
    for cid in set(per) | set(revenue):
        m = per.get(cid, {"meters": {}, "cost": 0})
        meters = m["meters"]
        rev, cost = revenue.get(cid) or 0, round(m["cost"])
        companies.append(
            {
                "id": cid,
                "name": names.get(cid, "—"),
                "calls": round(meters.get("calls", 0)),
                "minutes": round(meters.get("voice_minutes_inbound", 0) + meters.get("voice_minutes_outbound", 0)),
                "wa_messages": round(meters.get("whatsapp_messages", 0)),
                "ai_credits": round(meters.get("ai_credits", 0), 1),
                "cost": cost,
                "revenue": rev,
                "margin": rev - cost,
                "margin_percent": round((rev - cost) * 100 / rev) if rev else None,
            }
        )
    companies.sort(key=lambda r: (-r["revenue"], -r["cost"], r["name"]))
    providers = [
        {"provider": r["provider_key"] or "—", "meter": r["meter"], "quantity": r["q"] or 0, "cost": round(r["c"] or 0)}
        for r in events.exclude(provider_key="")
        .values("provider_key", "meter")
        .annotate(q=Sum("quantity"), c=Sum("provider_cost_paise"))
        .order_by("provider_key", "meter")
    ]
    total_rev, total_cost = sum(r["revenue"] for r in companies), sum(r["cost"] for r in companies)
    return {
        "start": start,
        "month": start.strftime("%Y-%m"),
        "companies": companies,
        "providers": providers,
        "revenue": total_rev,
        "cost": total_cost,
        "margin": total_rev - total_cost,
        "margin_percent": round((total_rev - total_cost) * 100 / total_rev) if total_rev else None,
    }
