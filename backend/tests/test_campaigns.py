# ruff: noqa: F811 — pytest fixtures imported from the voice tests
"""Phase 6 part 4: outbound calling campaigns (CAMP-01 … CAMP-06), compliance before every dial (CAMP-03, COMP-03 …
COMP-05) and the hot-lead / campaign alerts. Telephony is faked (no network)."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.agents import runtime
from apps.agents.models import Conversation
from apps.billing.models import Plan, PlanEntitlement
from apps.campaigns import services as campaigns
from apps.crm import services as crm
from apps.crm.models import Lead
from apps.notifications.models import Notification
from apps.rbac.models import Role
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member
from apps.voice import services as voice
from apps.voice.models import Call

from .conftest import make_user
from .test_voice_calls import WINDOW, FakeTelephony, line, realty, sara, twilio  # noqa: F401 — fixtures


@pytest.fixture
def fake(monkeypatch):
    return FakeTelephony(monkeypatch)


@pytest.fixture
def manager(realty):
    user = make_user("manager@alpha.example")
    add_member(realty, user.email, Role.objects.get(scope="company", key="manager"))
    return user


def request_for(user, company):
    req = RequestFactory().get("/")
    req.user, req.company = user, company
    return req


def leads(realty, n, **extra):
    out = []
    with company_context(realty.id):
        for i in range(n):
            out.append(
                crm.create_lead(
                    realty, {"name": f"Lead {i}", "phone": f"+91981234{i:04d}", "source": "manual", **extra}
                )
            )
    return out


def data(sara, **kw):
    return {
        "name": "New Town Leads",
        "employee": str(sara.pk),
        "brief": "Offer the New Town launch and a site visit.",
        "source": "filter",
        "windows": "00:00-23:59",
        "max_attempts": 3,
        "retry_gap_minutes": 30,
        "retry_outcomes": ["busy", "no_answer"],
        "follow_up_labels": [],
        "follow_up_after_days": 2,
        "max_concurrent": 1,
        "daily_limit": 50,
        **kw,
    }


def make(realty, sara, owner, n=3, **kw):
    lead_rows = leads(realty, n)
    with company_context(realty.id):
        c = campaigns.save_campaign(realty, data(sara, **kw), user=owner)
        campaigns.build_list(c, request_for(owner, realty))
    return c, lead_rows


def answer(call, status=Call.COMPLETED):
    with company_context(call.company_id):
        call.refresh_from_db()
        if status in (Call.COMPLETED,):
            voice.transition(call, Call.IN_PROGRESS)
        voice.transition(call, status)
        voice.finish(call)


def fresh(obj):
    with company_context(obj.company_id):
        obj.refresh_from_db()


def members(c, **kw):
    with company_context(c.company_id):
        return list(c.members.filter(**kw).order_by("created_at"))


# ---------------------------------------------------------------- CAMP-01 create and the list
@pytest.mark.django_db
def test_create_validates_against_calling_rules_plan_and_team(realty, sara, owner_a, set_setting):
    set_setting("calling.window_start", "09:00")
    set_setting("calling.window_end", "21:00")
    with company_context(realty.id):
        with pytest.raises(ValidationError, match="calling hours"):
            campaigns.save_campaign(realty, data(sara, windows="08:00-12:00"))
        with pytest.raises(ValidationError, match="Attempts per lead"):
            campaigns.save_campaign(realty, data(sara, windows="10:00-12:00", max_attempts=99))
        with pytest.raises(ValidationError, match="team's own numbers"):
            campaigns.save_campaign(
                realty, data(sara, windows="10:00-12:00", test_mode="on", test_numbers="+919800000001")
            )
        with pytest.raises(ValidationError, match="10:00-13:00"):
            campaigns.save_campaign(realty, data(sara, windows="ten to one"))
        c = campaigns.save_campaign(realty, data(sara, windows="14:00-17:00, 10:00-12:00", days=["mon", "sat"]))
    assert c.windows == [["10:00", "12:00"], ["14:00", "17:00"]] and c.days == ["mon", "sat"] and c.status == "draft"
    d = campaigns.defaults(realty)
    assert d["windows"] == [["09:00", "21:00"]] and d["max_attempts"] == 3


@pytest.mark.django_db
def test_list_from_filter_csv_and_picked_leads(realty, sara, owner_a):
    hot = leads(realty, 2, custom={"budget": "1 cr", "timeline": "Within 30 days"})
    with company_context(realty.id):
        crm.apply_event(hot[0], "appointment_booked")
        crm.create_lead(realty, {"name": "No phone", "email": "np@example.com"})
        c = campaigns.save_campaign(realty, data(sara, filter_params="score=hot"), user=owner_a)
        assert campaigns.build_list(c, request_for(owner_a, realty)) == (1, 0)
        c.filter_params = ""
        c.save()
        added, no_phone = campaigns.build_list(c, request_for(owner_a, realty))
        assert added == 2 and no_phone == 1
        # picked in the lead list (bulk action); duplicates are not added twice
        assert crm.bulk(realty, Lead.objects.all(), "add_to_campaign", str(c.pk), owner_a) == 0
        # CSV / Excel: new people become leads, existing ones are matched
        csv = SimpleUploadedFile("list.csv", b"Name,Phone\nAsha,+919811100001\nLead 0,+919812340000\n")
        c2 = campaigns.save_campaign(realty, data(sara, source="csv"), user=owner_a)
        assert campaigns.build_list(c2, request_for(owner_a, realty), csv) == (2, 0)
        assert Lead.objects.filter(phone="+919811100001", source__key="import").exists()
    with pytest.raises(ValidationError):
        with company_context(realty.id):
            campaigns.build_list(c2, request_for(owner_a, realty))  # no file


# ---------------------------------------------------------------- COMP-05 approval, CAMP-02 controls
@pytest.mark.django_db
def test_manager_asks_admin_approves_and_plan_limit(client, realty, sara, owner_a, manager, line, fake):
    c, _ = make(realty, sara, manager)
    client.force_login(manager)
    r = client.post(f"/app/campaigns/{c.pk}/", {"op": "approve"})
    assert r.status_code == 403  # a manager may not approve
    client.post(f"/app/campaigns/{c.pk}/", {"op": "request_approval"})
    alert = Notification.all_companies.get(user=owner_a, kind="campaign")
    assert "Approve the campaign" in alert.title and alert.url == f"/app/campaigns/{c.pk}/"
    client.force_login(owner_a)
    page = client.get(f"/app/campaigns/{c.pk}/").content.decode()
    assert "Waiting for approval" in page and "Approve &amp; start" in page
    plan = Plan.objects.order_by("sort_order").first()
    realty.plan = plan
    realty.save(update_fields=["plan"])
    PlanEntitlement.objects.update_or_create(plan=plan, key="campaigns", defaults={"limit_value": 0})
    client.post(f"/app/campaigns/{c.pk}/", {"op": "approve"})
    c.refresh_from_db()
    assert c.status == "draft"  # plan allows no active campaign
    PlanEntitlement.objects.filter(plan=plan, key="campaigns").update(limit_value=1)
    client.post(f"/app/campaigns/{c.pk}/", {"op": "approve"})
    c.refresh_from_db()
    assert c.status == "running" and c.approved_by == owner_a
    with company_context(realty.id):
        campaigns.pause(c)
        assert campaigns.dispatch_one(c) == 0
        campaigns.resume(c)
        with pytest.raises(ValidationError):
            campaigns.save_campaign(realty, data(sara), c)  # running: pause first
        campaigns.stop(c, "Budget changed", owner_a)
    c.refresh_from_db()
    assert c.status == "stopped" and {m.status for m in members(c)} == {"skipped"}
    assert Notification.all_companies.filter(kind="campaign", title__startswith="Campaign stopped").exists()


@pytest.mark.django_db
def test_scheduled_campaign_starts_on_its_date(realty, sara, owner_a, line, fake):
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    c, _ = make(realty, sara, owner_a, n=1, starts_on=tomorrow.isoformat())
    with company_context(realty.id):
        campaigns.approve(c, owner_a)
        assert c.status == "scheduled" and campaigns.dispatch_one(c) == 0
        later = timezone.now() + dt.timedelta(days=1, hours=1)
        assert campaigns.dispatch_one(c, later) == 1
    assert c.status == "running" and len(fake.calls) == 1


# ---------------------------------------------------------------- dialling, retries, results (CAMP-03, CAMP-04)
@pytest.mark.django_db
def test_dial_retry_connect_and_complete(realty, sara, owner_a, line, fake):
    c, lead_rows = make(realty, sara, owner_a, n=2)
    with company_context(realty.id):
        campaigns.approve(c, owner_a)
    assert campaigns.dispatch() == 1  # one at a time
    assert campaigns.dispatch() == 0  # still on the call
    first = members(c, status="calling")[0]
    call = Call.all_companies.get(campaign_member=first)
    assert call.reason == "campaign" and call.to_e164 == first.phone
    answer(call, Call.BUSY)  # → called again after the campaign's gap
    fresh(first)
    assert first.status == "pending" and first.attempts == 1 and first.next_attempt_at > timezone.now()
    assert not Call.all_companies.filter(retry_of=call).exists()  # the campaign retries, not the voice service
    assert campaigns.dispatch() == 1  # the other lead now
    second = members(c, status="calling")[0]
    answer(Call.all_companies.get(campaign_member=second))
    fresh(second)
    assert second.status == "done" and second.connected
    later = timezone.now() + dt.timedelta(minutes=31)
    assert campaigns.dispatch(later) == 1
    answer(Call.all_companies.filter(campaign_member=first).order_by("-queued_at").first())
    fresh(c)
    with company_context(realty.id):
        s = campaigns.stats(c)
    assert c.status == "completed" and s["connected"] == 2 and s["dialled"] == 2 and s["percent"] == 100
    done = Notification.all_companies.get(user=owner_a, kind="campaign", title__startswith="Campaign finished")
    assert "2 connected" in done.body


@pytest.mark.django_db
def test_compliance_before_every_dial(realty, sara, owner_a, line, fake, set_setting):
    c, lead_rows = make(realty, sara, owner_a, n=3)
    with company_context(realty.id):
        crm.update_lead(lead_rows[0], {"dnd": True})  # COMP-03 opt-out / Do-not-call
        Lead.objects.filter(pk=lead_rows[1].pk).update(source=None)  # COMP-05 no source, no consent
        campaigns.approve(c, owner_a)
        c.max_concurrent = 3
        c.save()
    assert campaigns.dispatch() == 1
    reasons = {m.lead_id: m.skip_reason for m in members(c, status="skipped")}
    assert "Do not call" in reasons[lead_rows[0].pk] and "consent" in reasons[lead_rows[1].pk]
    # with consent recorded the lead may be called; "opt-in only" setting needs an explicit opt-in
    set_setting("campaigns.require_opt_in", True)
    with company_context(realty.id):
        assert not campaigns._consent_ok(lead_rows[2])
        crm.record_consent(lead_rows[2], "voice", "opt_in", "test")
        assert campaigns._consent_ok(lead_rows[2])


@pytest.mark.django_db
def test_waits_outside_windows_days_and_company_limits(realty, sara, owner_a, line, fake, set_setting):
    c, _ = make(realty, sara, owner_a, n=2, windows="10:00-11:00")
    with company_context(realty.id):
        campaigns.approve(c, owner_a)
        night = timezone.make_aware(dt.datetime.combine(timezone.localdate(), dt.time(23, 0)))
        assert campaigns.dispatch_one(c, night) == 0
        assert c.waiting_reason.startswith("Outside")
        c.windows, c.days = [], [d for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") if d != _today_key()]
        c.save()
        assert campaigns.dispatch_one(c) == 0  # not a calling day
        c.days = []
        c.save()
    set_setting("calling.max_calls_per_day", 0)  # the company's daily cap: wait, never skip the lead
    with company_context(realty.id):
        assert campaigns.dispatch_one(c) == 0
        assert "today's call limit" in c.waiting_reason and not members(c, status="skipped")


def _today_key():
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[timezone.localdate().weekday()]


@pytest.mark.django_db
def test_results_and_follow_up_from_the_conversation(realty, sara, owner_a, line, fake):
    c, lead_rows = make(realty, sara, owner_a, n=1, follow_up_labels=["hot"], whatsapp_after_call="on")
    with company_context(realty.id):
        campaigns.approve(c, owner_a)
    campaigns.dispatch()
    member = members(c)[0]
    call = Call.all_companies.get(campaign_member=member)
    with company_context(realty.id):
        conv = runtime.start(sara, "voice", lead=lead_rows[0])
        conv.state = {**conv.state, "voice": True, "call": str(call.pk)}
        conv.save()
        call.conversation = conv
        call.save()
        assert "New Town Leads" in runtime.system_prompt(conv, []) and "site visit" in runtime.system_prompt(conv, [])
        lead = lead_rows[0]
        lead.custom = {"budget": "1 cr", "timeline": "Within 30 days"}
        lead.save()
        crm.apply_event(lead, "appointment_booked")  # → hot
        conv.summary = "Wants a 3 BHK, site visit booked."
        conv.status = Conversation.ENDED
        conv.save()
        campaigns.after_conversation(conv)
    fresh(member)
    assert member.hot and member.qualified and member.summary.startswith("Wants")
    assert Call.all_companies.filter(lead=lead_rows[0], reason="follow_up", status="queued").exists()
    with company_context(realty.id):
        activity = lead_rows[0].activities.filter(type="whatsapp").first()
    assert activity and "not sent" in activity.summary  # no approved template in the test


# ---------------------------------------------------------------- CAMP-06 test mode
@pytest.mark.django_db
def test_test_mode_calls_only_team_numbers(realty, sara, owner_a, line, fake):
    owner_a.phone = "+919800000077"
    owner_a.save()
    leads(realty, 3)
    with company_context(realty.id):
        c = campaigns.save_campaign(realty, data(sara, test_mode="on", test_numbers="+919800000077"), user=owner_a)
        assert campaigns.build_list(c, request_for(owner_a, realty)) == (1, 0)
        with pytest.raises(ValidationError):
            campaigns.add_leads(c, Lead.objects.all())
        campaigns.approve(c, owner_a)
    assert campaigns.dispatch() == 1
    call = Call.all_companies.get(campaign_member__campaign=c)
    assert call.reason == "campaign_test" and call.to_e164 == "+919800000077" and call.lead is None
    answer(call)
    fresh(c)
    with company_context(realty.id):
        assert c.status == "completed" and campaigns.stats(c)["connected"] == 1


# ---------------------------------------------------------------- CAMP-05 export, API, panel, isolation
@pytest.mark.django_db
def test_export_api_panel_and_isolation(client, realty, sara, owner_a, line, fake, company_b, owner_b):
    c, lead_rows = make(realty, sara, owner_a, n=2)
    client.force_login(owner_a)
    csv = client.get(f"/app/campaigns/{c.pk}/export/?format=csv").content.decode("utf-8-sig")
    assert csv.startswith("Lead ID,Name,Phone,Result") and "Lead 0" in csv and "Summary" in csv
    xlsx = client.get(f"/app/campaigns/{c.pk}/export/?format=xlsx")
    assert xlsx["Content-Type"].startswith("application/vnd.openxml")
    # API
    r = client.post("/api/v1/campaigns/", data(sara, name="API run"), content_type="application/json")
    assert r.status_code == 201, r.content
    pk = r.json()["id"]
    r = client.post(
        f"/api/v1/campaigns/{pk}/build/", {"lead_ids": [str(lead_rows[0].pk)]}, content_type="application/json"
    )
    assert r.json()["added"] == 1
    assert client.post(f"/api/v1/campaigns/{pk}/approve/").json()["status"] == "running"
    assert client.get(f"/api/v1/campaigns/{pk}/progress/").json()["stats"]["total"] == 1
    assert client.get(f"/api/v1/campaigns/{pk}/members/").json()["results"][0]["phone"] == lead_rows[0].phone
    assert client.patch(f"/api/v1/campaigns/{pk}/", {"name": "x"}, content_type="application/json").status_code == 400
    assert client.post(f"/api/v1/campaigns/{pk}/pause/").json()["status"] == "paused"
    assert (
        client.patch(f"/api/v1/campaigns/{pk}/", {"name": "Renamed"}, content_type="application/json").json()["name"]
        == "Renamed"
    )
    assert client.delete(f"/api/v1/campaigns/{pk}/").status_code == 400  # not a draft
    assert client.get(f"/api/v1/campaigns/{pk}/export/").status_code == 200
    # panel
    assert client.get("/app/campaigns/").status_code == 200
    assert "score%3Dhot" in client.get("/app/leads/?score=hot").content.decode()  # "Call these in a campaign"
    form = client.get("/app/campaigns/new/?filters=score%3Dhot").content.decode()
    assert 'value="score=hot"' in form and "Test mode" in form
    detail = client.get(f"/app/campaigns/{c.pk}/").content.decode()
    assert "Rebuild the list" in detail and "Lead 1" in detail
    # another company sees nothing
    client.force_login(owner_b)
    assert client.get(f"/app/campaigns/{c.pk}/").status_code == 404
    assert client.get(f"/api/v1/campaigns/{pk}/").status_code == 404
    assert client.get("/api/v1/campaigns/").json()["results"] == []
    assert Client().get("/api/v1/campaigns/").status_code in (401, 403)
