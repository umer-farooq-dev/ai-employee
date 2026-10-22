"""DASH-01 … DASH-05, EMP-13: the company's numbers for a date range and AI Employee, counted from the raw records
(calls, leads, score and status history, appointments, handoffs, usage) so the figures always match the lists.

Definitions (shown as hints on the dashboard):
- Calls: real calls queued in the range (tests excluded); Connected: of those, answered.
- Leads: new leads; Qualified / Hot: leads whose score reached a qualified label / Hot in the range.
- Conversions: leads moved to a "won" status in the range; Appointments: booked in the range, not cancelled.
- Human transfers: handoffs from real conversations; AI usage: AI credits used.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone

from apps.platform_config.services import get as setting

RANGES = [("today", "Today"), ("7d", "Last 7 days"), ("30d", "Last 30 days"), ("custom", "Custom")]
DAYS = {"today": 1, "7d": 7, "30d": 30}
SERIES = [
    ("leads", "Leads"),
    ("calls", "Calls"),
    ("connected", "Connected calls"),
    ("qualified", "Qualified leads"),
    ("appointments", "Appointments"),
    ("conversions", "Conversions"),
    ("usage", "AI usage (credits)"),
]


@dataclass
class Period:
    key: str
    first: date
    last: date
    start: datetime
    end: datetime
    tz: object

    @property
    def hourly(self):
        return self.first == self.last

    @property
    def label(self):
        if self.key in DAYS:
            return dict(RANGES)[self.key]
        return f"{self.first:%d %b %Y} – {self.last:%d %b %Y}"


def period(company, key="", first="", last="", now=None):
    """Range key (today / 7d / 30d / custom with ISO dates) in the company's timezone; end is exclusive."""
    from apps.agents.tools import company_tz

    tz = company_tz(company)
    today = timezone.localtime(now or timezone.now(), tz).date()
    key = key if key in dict(RANGES) else setting("analytics.default_range")
    if key == "custom":
        try:
            a, b = date.fromisoformat(str(first)), date.fromisoformat(str(last))
        except ValueError:
            raise ValidationError("Choose a start and an end date.") from None
        if a > b:
            a, b = b, a
        if b > today:
            b = today
        if (b - a).days + 1 > setting("analytics.max_range_days"):
            raise ValidationError(f"Choose up to {setting('analytics.max_range_days')} days.")
    else:
        a, b = today - timedelta(days=DAYS[key] - 1), today
    start = datetime.combine(a, time.min, tzinfo=tz)
    return Period(key, a, b, start, datetime.combine(b + timedelta(days=1), time.min, tzinfo=tz), tz)


def _won_keys(company):
    from apps.industries import services as templates
    from apps.industries.models import LeadStatus

    return [s.key for s in templates.statuses(company) if s.category == LeadStatus.WON]


def querysets(company, p, employee=None):
    """The record sets every figure is counted from; `employee` narrows each to one AI Employee."""
    from apps.agents.models import UsageEvent
    from apps.crm.models import Lead, LeadActivity, LeadScoreEvent
    from apps.scheduling.models import Appointment
    from apps.voice.models import Call, Handoff

    rng = {"created_at__gte": p.start, "created_at__lt": p.end}
    sets = {
        "calls": Call.objects.filter(company=company, queued_at__gte=p.start, queued_at__lt=p.end).exclude(
            reason__in=Call.TEST_REASONS
        ),
        "leads": Lead.objects.filter(company=company, deleted_at__isnull=True, merged_into__isnull=True, **rng),
        "scores": LeadScoreEvent.objects.filter(company=company, lead__deleted_at__isnull=True, **rng),
        "won": LeadActivity.objects.filter(
            company=company,
            type="status_change",
            data__new__in=_won_keys(company),
            lead__deleted_at__isnull=True,
            **rng,
        ),
        "appointments": Appointment.objects.filter(company=company, **rng).exclude(status=Appointment.CANCELLED),
        "handoffs": Handoff.objects.filter(company=company, conversation__is_test=False, **rng),
        "usage": UsageEvent.objects.filter(
            company=company, meter="ai_credits", occurred_at__gte=p.start, occurred_at__lt=p.end
        ),
    }
    if employee:
        eid = getattr(employee, "pk", employee)
        sets["calls"] = sets["calls"].filter(employee_id=eid)
        sets["usage"] = sets["usage"].filter(employee_id=eid)
        sets["handoffs"] = sets["handoffs"].filter(conversation__employee_id=eid)
        for name, field in (("leads", ""), ("scores", "lead__"), ("won", "lead__"), ("appointments", "lead__")):
            sets[name] = sets[name].filter(**{f"{field}assigned_ai_employee_id": eid})
    return sets


def _qualified(scores):
    return scores.filter(label__in=setting("campaigns.qualified_labels"))


def kpis(company, p, employee=None):
    """DASH-01 cards."""
    from apps.agents.models import AIEmployee
    from apps.crm.models import Lead

    s = querysets(company, p, employee)
    staff = AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED)
    calls = s["calls"].aggregate(total=Count("pk"), connected=Count("pk", filter=Q(answered_at__isnull=False)))
    leads = s["leads"].count()
    conversions = s["won"].values("lead").distinct().count()
    return {
        "ai_employees": staff.count(),
        "ai_employees_active": staff.filter(status=AIEmployee.ACTIVE).count(),
        "calls": calls["total"],
        "connected": calls["connected"],
        "connect_rate": round(calls["connected"] * 100 / calls["total"]) if calls["total"] else 0,
        "leads": leads,
        "qualified": _qualified(s["scores"]).values("lead").distinct().count(),
        "hot": s["scores"].filter(label=Lead.HOT).values("lead").distinct().count(),
        "appointments": s["appointments"].count(),
        "conversions": conversions,
        "conversion_rate": round(conversions * 100 / leads) if leads else 0,
        "transfers": s["handoffs"].count(),
        "usage": round(s["usage"].aggregate(v=Sum("quantity"))["v"] or 0),
    }


def series(company, p, employee=None):
    """DASH-02: one point per hour (a single day) or per day for each chart line."""
    s = querysets(company, p, employee)
    trunc = TruncHour if p.hourly else TruncDate

    def bucket(qs, field, value=None):
        rows = qs.annotate(b=trunc(field, tzinfo=p.tz)).values("b").annotate(v=value or Count("pk"))
        out = {}
        for r in rows:
            b = r["b"]
            key = timezone.localtime(b, p.tz).hour if p.hourly else b
            out[key] = round(r["v"] or 0, 1)
        return out

    raw = {
        "leads": bucket(s["leads"], "created_at"),
        "calls": bucket(s["calls"], "queued_at"),
        "connected": bucket(s["calls"].filter(answered_at__isnull=False), "queued_at"),
        "qualified": bucket(_qualified(s["scores"]), "created_at", Count("lead", distinct=True)),
        "appointments": bucket(s["appointments"], "created_at"),
        "conversions": bucket(s["won"], "created_at", Count("lead", distinct=True)),
        "usage": bucket(s["usage"], "occurred_at", Sum("quantity")),
    }
    if p.hourly:
        keys, labels = list(range(24)), [f"{h:02d}:00" for h in range(24)]
    else:
        keys = [p.first + timedelta(days=i) for i in range((p.last - p.first).days + 1)]
        labels = [k.isoformat() for k in keys]
    return {"labels": labels, "series": {name: [raw[name].get(k, 0) for k in keys] for name, _ in SERIES}}


def employees(company, p):
    """DASH-03 / EMP-13: the same figures per AI Employee."""
    from apps.agents.models import AIEmployee
    from apps.crm.models import Lead

    s = querysets(company, p)

    def per(qs, field, value=None):
        return {r[field]: r["v"] for r in qs.values(field).annotate(v=value or Count("pk")) if r[field]}

    calls = per(s["calls"], "employee_id")
    connected = per(s["calls"].filter(answered_at__isnull=False), "employee_id")
    leads = per(s["leads"], "assigned_ai_employee_id")
    qualified = per(_qualified(s["scores"]), "lead__assigned_ai_employee_id", Count("lead", distinct=True))
    hot = per(s["scores"].filter(label=Lead.HOT), "lead__assigned_ai_employee_id", Count("lead", distinct=True))
    appts = per(s["appointments"], "lead__assigned_ai_employee_id")
    won = per(s["won"], "lead__assigned_ai_employee_id", Count("lead", distinct=True))
    transfers = per(s["handoffs"], "conversation__employee_id")
    usage = per(s["usage"], "employee_id", Sum("quantity"))
    rows = []
    for e in AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED).order_by("name"):
        rows.append(
            {
                "id": str(e.pk),
                "name": e.name,
                "status": e.get_status_display(),
                "calls": calls.get(e.pk, 0),
                "connected": connected.get(e.pk, 0),
                "leads": leads.get(e.pk, 0),
                "qualified": qualified.get(e.pk, 0),
                "hot": hot.get(e.pk, 0),
                "appointments": appts.get(e.pk, 0),
                "conversions": won.get(e.pk, 0),
                "transfers": transfers.get(e.pk, 0),
                "usage": round(usage.get(e.pk, 0)),
            }
        )
    return rows


FUNNEL = [
    ("total", "In the list"),
    ("dialled", "Dialled"),
    ("connected", "Connected"),
    ("qualified", "Qualified"),
    ("hot", "Hot"),
    ("appointments", "Appointments"),
]


def campaigns(company, p, employee=None):
    """DASH-04: funnel per campaign that was running in the range (drafts left out)."""
    from apps.campaigns import services as camp
    from apps.campaigns.models import Campaign

    qs = (
        Campaign.objects.filter(company=company, started_at__isnull=False, started_at__lt=p.end)
        .filter(Q(finished_at__isnull=True) | Q(finished_at__gte=p.start))
        .select_related("employee")
        .order_by("-started_at")
    )
    if employee:
        qs = qs.filter(employee_id=getattr(employee, "pk", employee))
    out = []
    for c in qs[:20]:
        st = camp.stats(c)
        out.append(
            {
                "id": str(c.pk),
                "name": c.name,
                "employee": c.employee.name,
                "status": c.get_status_display(),
                "funnel": [{"key": k, "label": label, "value": st[k]} for k, label in FUNNEL],
            }
        )
    return out


def report(company, p, employee=None, parts=("kpis", "series")):
    data = {"period": {"key": p.key, "label": p.label, "from": p.first.isoformat(), "to": p.last.isoformat()}}
    for part in parts:
        data[part] = employees(company, p) if part == "employees" else globals()[part](company, p, employee)
    return data
