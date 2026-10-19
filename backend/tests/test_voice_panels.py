"""Phase 5 part 5: company panel (calls, Call now, calling rules, wizard voice / number / handoff) and Super Admin
Calls (VOICE-15, EMP-05, EMP-08, CP-06, CRM-11, SA-15)."""

import pytest
from django.test import Client
from django.utils import timezone

from apps.agents import services as employees
from apps.agents.models import AIEmployee
from apps.audit.models import AuditLog
from apps.crm import services as crm
from apps.industries.models import Industry
from apps.providers import services as providers
from apps.providers.models import Language, Provider, Voice
from apps.rbac.models import Role
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member
from apps.voice import services
from apps.voice.models import Call, PhoneNumber

from .conftest import make_user
from .test_voice_calls import FakeTelephony


@pytest.fixture
def realty(company_a, set_setting):
    set_setting("calling.window_start", "00:00")
    set_setting("calling.window_end", "23:59")
    industry = Industry.objects.get(key="real-estate")
    company_a.industry, company_a.template_version = industry, industry.published_version
    company_a.save()
    return company_a


@pytest.fixture
def sara(realty):
    with company_context(realty.id):
        emp = employees.create_employee(realty, {"role": "sales_executive", "name": "Sara"})
    AIEmployee.all_companies.filter(pk=emp.pk).update(status=AIEmployee.ACTIVE)
    emp.refresh_from_db()
    return emp


@pytest.fixture
def number(realty, sara):
    p = Provider.objects.get(key="twilio")
    p.api_key, p.config, p.is_active = "tw-secret", {"account_sid": "AC1"}, True
    p.save()
    n = services.save_number(None, {"provider": "twilio", "e164": "+918045678901", "company": str(realty.pk)})
    with company_context(realty.id):
        return services.connect_number(realty, n, sara)


def member(company, email, role="owner"):
    user = make_user(email)
    add_member(company, email, Role.objects.get(scope="company", key=role))
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def owner(realty):
    return member(realty, "owner@realty.example")


@pytest.fixture
def lead(realty):
    with company_context(realty.id):
        return crm.create_lead(realty, {"name": "Ravi", "phone": "+919876543210"})


# ---------------------------------------------------------------- calls list / detail (VOICE-15)
@pytest.mark.django_db
def test_call_log_and_detail(monkeypatch, owner, realty, sara, number, lead, company_b):
    FakeTelephony(monkeypatch)
    with company_context(realty.id):
        call = services.place_call(sara, lead)
        Call.objects.filter(pk=call.pk).update(
            status=Call.COMPLETED,
            duration_sec=95,
            recording_status="stored",
            recording_seconds=95,
            metrics={
                "p50_ms": 900,
                "p95_ms": 2400,
                "turns": [{"stt_ms": 200, "llm_ms": 500, "tts_ms": 150, "total_ms": 900}],
            },
        )
    html = owner.get("/app/calls/").content.decode()
    assert "Ravi" in html and "Completed" in html and "95s" in html
    assert "Calls" in owner.get("/app/").content.decode()  # menu item
    html = owner.get(f"/app/calls/{call.pk}/").content.decode()
    assert "Play recording" in html and "Download" in html and "2400 ms" in html and "text-danger" in html
    agent = member(realty, "agent@realty.example", "agent")
    html = agent.get(f"/app/calls/{call.pk}/").content.decode()
    assert "Play recording" in html and "Download" not in html  # agents may listen, not download
    other = member(company_b, "owner@beta.example")
    assert other.get(f"/app/calls/{call.pk}/").status_code == 404

    # VOICE-14: follow-up need and the appointment booked on the call (page + API)
    from apps.agents import runtime
    from apps.agents.models import ToolInvocation

    with company_context(realty.id):
        conv = runtime.start(sara, "voice", {}, lead=lead)
        conv.summary, conv.follow_up_required = "Wants a site visit.", True
        conv.save()
        booked = {"booked": True, "appointment_number": "AP-000007", "type": "Site visit", "when": "Sunday 22 Nov"}
        ToolInvocation.objects.create(
            company=realty, conversation=conv, tool_key="book_appointment", output=booked, idempotency_key="t1"
        )
        Call.objects.filter(pk=call.pk).update(conversation=conv)
    html = owner.get(f"/app/calls/{call.pk}/").content.decode()
    assert "Needed" in html and "AP-000007" in html and "Sunday 22 Nov" in html
    data = owner.get(f"/api/v1/calls/{call.pk}/").json()
    assert data["follow_up_required"] is True and data["appointments"][0]["appointment_number"] == "AP-000007"


# ---------------------------------------------------------------- Call now from the lead (CRM-11, VOICE-02)
@pytest.mark.django_db
def test_call_now_and_schedule_from_the_lead(monkeypatch, owner, realty, sara, number, lead):
    fake = FakeTelephony(monkeypatch)
    html = owner.get(f"/app/leads/{lead.pk}/").content.decode()
    assert "AI call" in html and "Call now" in html and "Sara" in html
    r = owner.post(f"/app/leads/{lead.pk}/call/", {"employee": str(sara.pk)}, follow=True)
    assert "is calling Ravi now" in r.content.decode() and fake.calls
    r = owner.post(
        f"/app/leads/{lead.pk}/call/",
        {"employee": str(sara.pk), "schedule": "1", "when": "2030-01-05T11:00"},
        follow=True,
    )
    assert "will call Ravi" in r.content.decode()
    with company_context(realty.id):
        assert Call.objects.filter(lead=lead, reason="follow_up", status=Call.QUEUED).exists()
        crm.update_lead(lead, {"dnd": True})
    r = owner.post(f"/app/leads/{lead.pk}/call/", {"employee": str(sara.pk)}, follow=True)
    assert "opted out" in r.content.decode()
    html = owner.get(f"/app/leads/{lead.pk}/").content.decode()
    assert "/app/calls/" in html  # timeline links to the call


# ---------------------------------------------------------------- calling rules & numbers (CP-06)
@pytest.mark.django_db
def test_calling_settings_page(owner, realty, sara, number, set_setting):
    set_setting("calling.window_start", "09:00")
    set_setting("calling.window_end", "21:00")
    html = owner.get("/app/settings/calling/").content.decode()
    assert "+918045678901" in html and "Earliest 09:00" in html
    r = owner.post("/app/settings/calling/", {"op": "rules", "window_start": "08:00"}, follow=True)
    assert "platform limit" in r.content.decode()
    owner.post("/app/settings/calling/", {"op": "rules", "window_start": "10:00", "max_calls_per_day": "40"})
    realty.refresh_from_db()
    assert realty.settings["calling"] == {"window_start": "10:00", "max_calls_per_day": 40, "recording_enabled": False}
    owner.post("/app/settings/calling/", {"op": "number", "number": str(number.pk), "employee": ""})
    assert PhoneNumber.objects.get(pk=number.pk).employee is None
    agent = member(realty, "agent@realty.example", "agent")
    r = agent.post(
        "/app/settings/calling/", {"op": "number", "number": str(number.pk), "employee": str(sara.pk)}, follow=True
    )
    assert "may not change" in r.content.decode()


# ---------------------------------------------------------------- wizard: voice, number, handoff rules (EMP-05, EMP-08)
@pytest.mark.django_db
def test_wizard_voice_number_and_handoff_steps(owner, realty, sara, number):
    sarvam = Provider.objects.get(key="sarvam")
    sarvam.api_key, sarvam.is_active = "k", True
    sarvam.save()
    en = Language.objects.get(code="en")
    anushka = Voice.objects.get(provider=sarvam, language=en, provider_voice_id="anushka")
    vidya = Voice.objects.get(provider=sarvam, language=en, provider_voice_id="vidya")
    providers.save_speech_routes(en, "tts", [{"provider": "sarvam", "model": "bulbul:v2", "voice": str(anushka.pk)}])
    html = owner.get(f"/app/ai-employees/{sara.pk}/setup/voice/").content.decode()
    assert "Vidya" in html and "default: Anushka" in html
    owner.post(f"/app/ai-employees/{sara.pk}/setup/voice/", {"voice_en": str(vidya.pk), "speed": "1.1", "then": "stay"})
    sara.refresh_from_db()
    assert sara.voices == {"en": str(vidya.pk), "speed": 1.1}
    hi_voice = Voice.objects.get(provider=sarvam, language__code="hi", provider_voice_id="vidya")
    r = owner.post(
        f"/app/ai-employees/{sara.pk}/setup/voice/", {"voice_en": str(hi_voice.pk), "then": "stay"}, follow=True
    )
    assert "Choose a voice from the catalogue" in r.content.decode()

    html = owner.get(f"/app/ai-employees/{sara.pk}/setup/tools/").content.decode()
    assert "+918045678901" in html
    tools = [t.key for t in __import__("apps.agents.tools", fromlist=["available"]).available(sara)]
    owner.post(f"/app/ai-employees/{sara.pk}/setup/tools/", {"tools": tools, "phone_number": "", "then": "stay"})
    assert PhoneNumber.objects.get(pk=number.pk).employee is None
    owner.post(
        f"/app/ai-employees/{sara.pk}/setup/tools/", {"tools": tools, "phone_number": str(number.pk), "then": "stay"}
    )
    assert PhoneNumber.objects.get(pk=number.pk).employee_id == sara.pk

    r = owner.get(f"/app/ai-employees/{sara.pk}/setup/rules/").content.decode()
    assert "Hand over a call or chat when the customer says" in r
    owner.post(
        f"/app/ai-employees/{sara.pk}/setup/rules/",
        {"handoff_keywords": "complaint\nmanager", "handoff_on_hot_lead": "on", "recording": "on", "then": "stay"},
    )
    sara.refresh_from_db()
    assert sara.rules["handoff_keywords"] == ["complaint", "manager"] and sara.rules["handoff_on_hot_lead"] is True


# ---------------------------------------------------------------- Super Admin Calls (SA-15)
@pytest.mark.django_db
def test_super_admin_calls(monkeypatch, admin_client, support, realty, sara, number, lead):
    FakeTelephony(monkeypatch)
    with company_context(realty.id):
        call = services.place_call(sara, lead)
        Call.objects.filter(pk=call.pk).update(
            status=Call.COMPLETED,
            metrics={"p50_ms": 1500, "p95_ms": 3000, "errors": [{"stage": "tts", "error": "x"}]},
            ended_at=timezone.now(),
        )
    html = admin_client.get("/superadmin/calls/").content.decode()
    assert realty.name in html and "1500 / 3000 ms" in html and "Slow calls" in html
    assert realty.name in admin_client.get("/superadmin/calls/?slow=1").content.decode()
    html = admin_client.get(f"/superadmin/calls/{call.pk}/").content.decode()
    assert "tts: x" in html and "Timeline" in html
    r = admin_client.get(f"/superadmin/calls/{call.pk}/recording/", follow=True)
    assert "no stored recording" in r.content.decode()
    c = Client()
    c.force_login(support)
    assert c.get("/superadmin/calls/").status_code in (302, 403)
    assert not AuditLog.objects.filter(action="recording.listen").exists()
