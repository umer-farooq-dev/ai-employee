# ruff: noqa: F811 — pytest fixtures imported from the voice tests
"""Phase 7 part 1: company dashboard and analytics (DASH-01 … DASH-05, EMP-13). Figures must match the raw records."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.agents import services as employees
from apps.agents.models import Conversation, UsageEvent
from apps.analytics import services as analytics
from apps.crm import services as crm
from apps.crm.models import Lead, LeadScoreEvent
from apps.rbac.models import Role
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member
from apps.voice.models import Call, Handoff

from .conftest import make_user
from .test_voice_calls import WINDOW, realty, sara  # noqa: F401 — fixtures

API = "/api/v1/analytics/"


def seed(company, emp, other=None):
    """Two real calls (one answered), one test call, three leads (two qualified, one hot, one won), a handoff, usage."""
    now = timezone.now()
    with company_context(company.id):
        Call.objects.create(company=company, employee=emp, answered_at=now)
        Call.objects.create(company=company, employee=emp)
        Call.objects.create(company=company, employee=emp, reason="test_call", answered_at=now)
        rows = [crm.create_lead(company, {"name": f"L{i}", "phone": f"+9198100000{i:02d}"}) for i in range(3)]
        Lead.objects.filter(pk__in=[r.pk for r in rows]).update(assigned_ai_employee_id=emp.pk)
        for lead, label in ((rows[0], "hot"), (rows[1], "warm"), (rows[2], "cold")):
            LeadScoreEvent.objects.create(company=company, lead=lead, label=label, value=10)
        crm.set_status(rows[0], "converted")
        conv = Conversation.objects.create(company=company, employee=emp, channel="voice")
        Handoff.objects.create(company=company, conversation=conv)
        test_conv = Conversation.objects.create(company=company, employee=emp, channel="test", is_test=True)
        Handoff.objects.create(company=company, conversation=test_conv)
        UsageEvent.objects.create(company=company, employee=emp, meter="ai_credits", quantity=12.4, unit="credits")
        if other:
            Call.objects.create(company=company, employee=other)
    return rows


@pytest.mark.django_db
def test_kpis_series_and_employee_filter(realty, sara):
    with company_context(realty.id):
        other = employees.create_employee(realty, {"role": "sales_executive", "name": "Ravi"})
    seed(realty, sara, other)
    with company_context(realty.id):
        p = analytics.period(realty, "7d")
        k = analytics.kpis(realty, p)
        assert k["calls"] == 3 and k["connected"] == 1 and k["connect_rate"] == 33  # test call left out
        assert k["leads"] == 3 and k["qualified"] == 2 and k["hot"] == 1  # hot + warm qualify (setting)
        assert k["conversions"] == 1 and k["conversion_rate"] == 33
        assert k["transfers"] == 1 and k["usage"] == 12 and k["ai_employees"] == 2
        s = analytics.series(realty, p)
        assert len(s["labels"]) == 7 and sum(s["series"]["calls"]) == 3 and sum(s["series"]["qualified"]) == 2
        assert sum(s["series"]["conversions"]) == 1 and sum(s["series"]["leads"]) == 3
        today = analytics.series(realty, analytics.period(realty, "today"))
        assert len(today["labels"]) == 24 and sum(today["series"]["calls"]) == 3
        only = analytics.kpis(realty, p, other)
        assert only["calls"] == 1 and only["leads"] == 0 and only["usage"] == 0
        rows = {r["name"]: r for r in analytics.employees(realty, p)}
        assert rows["Sara"]["calls"] == 2 and rows["Sara"]["qualified"] == 2 and rows["Sara"]["conversions"] == 1
        assert rows["Ravi"]["calls"] == 1 and rows["Sara"]["transfers"] == 1


@pytest.mark.django_db
def test_period_rules(realty, set_setting):
    with company_context(realty.id):
        set_setting("analytics.default_range", "30d")
        assert analytics.period(realty).key == "30d"
        today = timezone.localdate()
        p = analytics.period(realty, "custom", today.isoformat(), (today - dt.timedelta(days=3)).isoformat())
        assert p.first < p.last and (p.last - p.first).days == 3  # swapped
        set_setting("analytics.max_range_days", 7)
        with pytest.raises(Exception, match="up to 7 days"):
            analytics.period(realty, "custom", (today - dt.timedelta(days=30)).isoformat(), today.isoformat())
        with pytest.raises(Exception, match="start and an end"):
            analytics.period(realty, "custom", "nope", "")


@pytest.mark.django_db
def test_api_pages_and_permissions(client, realty, sara, owner_a, company_b, owner_b):
    seed(realty, sara)
    client.force_login(owner_a)
    r = client.get(API, {"range": "7d", "parts": "kpis,series,employees,campaigns"})
    assert r.status_code == 200 and r.json()["kpis"]["calls"] == 2
    assert {"labels", "series"} <= set(r.json()["series"]) and r.json()["employees"][0]["name"] == "Sara"
    assert client.get(API, {"range": "custom", "from": "x"}).status_code == 400
    assert client.get(API, {"employee": "00000000-0000-0000-0000-000000000000"}).status_code == 400
    for url in ("/app/", "/app/analytics/", f"/app/analytics/?employee={sara.pk}&range=30d"):
        page = client.get(url)
        assert page.status_code == 200 and b"Qualified leads" in page.content
    # another company sees only its own numbers (TEN-01)
    client.force_login(owner_b)
    assert client.get(API).json()["kpis"]["calls"] == 0
    # a human agent has no company-wide figures: no API, no page, plain dashboard
    agent = make_user("agent@alpha.example")
    add_member(realty, agent.email, Role.objects.get(scope="company", key="agent"))
    client.force_login(agent)
    assert client.get(API).status_code == 403
    assert client.get("/app/analytics/").status_code == 403
    home = client.get("/app/")
    assert home.status_code == 200 and b"an-kpis" not in home.content


@pytest.mark.django_db
def test_campaign_funnel(realty, sara):
    from apps.campaigns.models import Campaign, CampaignMember

    rows = seed(realty, sara)
    with company_context(realty.id):
        draft = Campaign.objects.create(company=realty, name="Draft", employee=sara)
        live = Campaign.objects.create(
            company=realty, name="Launch", employee=sara, status=Campaign.RUNNING, started_at=timezone.now()
        )
        for i, lead in enumerate(rows):
            CampaignMember.objects.create(
                company=realty, campaign=live, lead=lead, phone=lead.phone, attempts=1, connected=i < 2, hot=i == 0
            )
        out = analytics.campaigns(realty, analytics.period(realty, "7d"))
    assert [c["name"] for c in out] == ["Launch"] and draft.pk
    funnel = {s["key"]: s["value"] for s in out[0]["funnel"]}
    assert funnel == {"total": 3, "dialled": 3, "connected": 2, "qualified": 0, "hot": 1, "appointments": 0}
