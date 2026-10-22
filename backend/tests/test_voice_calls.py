"""Phase 5 part 2: phone numbers, calls, telephony webhooks, compliance, retries (VOICE-01, 02, 16 … 18, COMP-02 … 04,
SEC-13). Telephony HTTP calls are faked — no network."""

import base64
import datetime as dt
import hashlib
import hmac
import urllib.parse

import pytest
from django.test import Client
from django.utils import timezone

from apps.agents import services as employees
from apps.agents.models import AIEmployee, Message, UsageEvent
from apps.billing.models import Plan, PlanEntitlement
from apps.crm import services as crm
from apps.crm.models import ConsentRecord, LeadActivity
from apps.industries.models import Industry
from apps.providers.models import Provider
from apps.rbac.models import Role
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member
from apps.voice import services, telephony
from apps.voice.models import Call, PhoneNumber

from .conftest import make_user

NUMBERS = "/api/v1/admin/phone-numbers/"
WINDOW = {"calling.window_start": "00:00", "calling.window_end": "23:59"}


class FakeTelephony:
    def __init__(self, monkeypatch, fail=False):
        self.calls, self.fail, self.n = [], fail, 0
        monkeypatch.setattr(telephony, "_form", self.form)
        monkeypatch.setattr(telephony, "_request", self.form)

    def form(self, method, url, headers, data, timeout=30):
        self.calls.append({"method": method, "url": url, "data": data})
        if self.fail:
            raise telephony.ProviderError("HTTP 400: invalid number")
        self.n += 1
        return {"sid": f"CA{self.n:04d}"}


@pytest.fixture
def twilio(db):
    p = Provider.objects.get(key="twilio")
    p.api_key, p.config, p.is_active = "tw-secret", {"account_sid": "AC1"}, True
    p.save()
    return p


@pytest.fixture
def realty(company_a, set_setting):
    for k, v in WINDOW.items():
        set_setting(k, v)
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
def line(twilio, realty, sara):
    number = services.save_number(None, {"provider": "twilio", "e164": "+918045678901", "company": str(realty.pk)})
    with company_context(realty.id):
        return services.connect_number(realty, number, sara)


@pytest.fixture
def lead(realty):
    with company_context(realty.id):
        return crm.create_lead(realty, {"name": "Ravi", "phone": "+919876543210"})


def twilio_post(client, provider, action, params, query=None, secret="tw-secret"):
    url = services.webhook_url(provider, action, **(query or {}))
    signed = url + "".join(k + str(params[k]) for k in sorted(params))
    sig = base64.b64encode(hmac.new(secret.encode(), signed.encode(), hashlib.sha1).digest()).decode()
    path = url.replace("http://127.0.0.1:8000", "")
    return client.post(path, params, HTTP_X_TWILIO_SIGNATURE=sig)


# ---------------------------------------------------------------- number pool (VOICE-16)
@pytest.mark.django_db
def test_number_pool_and_company_connection(admin_client, twilio, realty, sara, company_b):
    r = admin_client.post(NUMBERS, {"provider": "twilio", "e164": "12345"}, content_type="application/json")
    assert r.status_code == 400  # not a phone number
    r = admin_client.post(
        NUMBERS, {"provider": "twilio", "e164": "+918045678901", "label": "Sales"}, content_type="application/json"
    )
    assert r.status_code == 201, r.content
    assert r.json()["capabilities"] == ["inbound", "outbound"] and r.json()["company"] == ""
    dup = admin_client.post(NUMBERS, {"provider": "twilio", "e164": "+918045678901"}, content_type="application/json")
    assert dup.status_code == 400
    bad = admin_client.post(NUMBERS, {"provider": "sarvam", "e164": "+918045678902"}, content_type="application/json")
    assert bad.status_code == 400 and "telephony" in bad.json()["error"]["details"][0]
    pk = r.json()["id"]
    r = admin_client.patch(f"{NUMBERS}{pk}/", {"company": str(realty.pk)}, content_type="application/json")
    assert r.json()["company_name"] == realty.name

    owner = make_user("owner@realty.example")
    add_member(realty, owner.email, Role.objects.get(scope="company", key="owner"))
    c = Client()
    c.force_login(owner)
    assert [n["e164"] for n in c.get("/api/v1/phone-numbers/").json()] == ["+918045678901"]
    r = c.patch(f"/api/v1/phone-numbers/{pk}/", {"employee": str(sara.pk)}, content_type="application/json")
    assert r.status_code == 200 and r.json()["employee_name"] == "Sara"
    # given to another company → disconnected from the old AI Employee
    admin_client.patch(f"{NUMBERS}{pk}/", {"company": str(company_b.pk)}, content_type="application/json")
    number = PhoneNumber.objects.get(pk=pk)
    assert number.company == company_b and number.employee is None
    assert c.get("/api/v1/phone-numbers/").json() == []
    assert c.patch(f"/api/v1/phone-numbers/{pk}/", {"employee": str(sara.pk)}, "application/json").status_code == 404


# ---------------------------------------------------------------- Call now + compliance (VOICE-02, COMP-02 … 04)
@pytest.mark.django_db
def test_call_now_dials_through_the_provider(monkeypatch, line, sara, lead, realty):
    fake = FakeTelephony(monkeypatch)
    with company_context(realty.id):
        call = services.place_call(sara, lead)
    sent = fake.calls[-1]
    assert sent["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC1/Calls.json"
    assert sent["data"]["To"] == "+919876543210" and sent["data"]["From"] == "+918045678901"
    assert f"call={call.pk}" in sent["data"]["Url"] and services.webhook_token(line.provider) in sent["data"]["Url"]
    assert sent["data"]["MachineDetection"] == "Enable" and sent["data"]["TimeLimit"] == 15 * 60
    assert call.provider_call_id == "CA0001" and call.status == Call.QUEUED and call.direction == "outbound"

    FakeTelephony(monkeypatch, fail=True)
    with company_context(realty.id):
        failed = services.place_call(sara, lead)
    assert failed.status == Call.FAILED and "invalid number" in failed.error


@pytest.mark.django_db
def test_test_call_to_own_phone(monkeypatch, line, sara, realty):
    """EMP-10: draft employees too, no lead / consent needed; never retried; the API defaults to the profile phone."""
    fake = FakeTelephony(monkeypatch)
    AIEmployee.all_companies.filter(pk=sara.pk).update(status=AIEmployee.DRAFT)
    owner = make_user("owner@realty.example")
    owner.phone = "+919811112222"
    owner.save()
    add_member(realty, owner.email, Role.objects.get(scope="company", key="owner"))
    c = Client()
    c.force_login(owner)
    r = c.post(f"/api/v1/ai-employees/{sara.pk}/test-call/", {}, content_type="application/json")
    assert r.status_code == 201, r.content
    assert r.json()["to"] == "+919811112222" and fake.calls[-1]["data"]["To"] == "+919811112222"
    call = Call.all_companies.get(pk=r.json()["call"])
    assert call.reason == "test_call" and call.lead is None and call.from_e164 == line.e164
    bad = c.post(f"/api/v1/ai-employees/{sara.pk}/test-call/", {"phone": "+15550001111"}, "application/json")
    assert bad.status_code == 400  # allowed countries still apply
    with company_context(realty.id):
        call.status = Call.BUSY
        assert services.schedule_retry(call) is None


@pytest.mark.django_db
def test_stt_and_tts_usage_is_metered(line, sara, realty):
    with company_context(realty.id):
        conv = runtime_start(sara)
        Message.objects.create(company=realty, conversation=conv, role="ai", content="Namaste!")
        Message.objects.create(
            company=realty, conversation=conv, role="ai", content="Never said", meta={"unspoken": True}
        )
        call = Call.objects.create(
            company=realty,
            employee=sara,
            conversation=conv,
            direction="inbound",
            status=Call.COMPLETED,
            duration_sec=42,
            metrics={"providers": {"stt": '["sarvam/saarika-v2", "deepgram/nova-3"]', "tts": '["sarvam/bulbul"]'}},
        )
        services.finish(call)
    usage = {u.meter: u for u in UsageEvent.all_companies.filter(conversation=conv)}
    assert usage["stt_seconds"].quantity == 42 and usage["stt_seconds"].provider_key == "sarvam"
    assert usage["tts_characters"].quantity == len("Namaste!")


def runtime_start(employee):
    from apps.agents import runtime

    conv = runtime.start(employee, "voice", {})
    conv.messages.all().delete()  # only the lines written by the test count
    return conv


@pytest.mark.django_db
def test_calls_that_never_report_back_are_closed(monkeypatch, line, sara, lead, realty):
    FakeTelephony(monkeypatch)
    with company_context(realty.id):
        dialled = services.place_call(sara, lead)  # queued with a provider id, no webhook ever arrives
        talking = Call.objects.create(company=realty, employee=sara, direction="inbound", status=Call.IN_PROGRESS)
    now = timezone.now()
    services.sweep_stuck(now + dt.timedelta(minutes=3))  # past the ring time, not past the longest call
    dialled.refresh_from_db()
    talking.refresh_from_db()
    assert dialled.status == Call.FAILED and "No update" in dialled.error
    assert talking.status == Call.IN_PROGRESS
    services.sweep_stuck(now + dt.timedelta(minutes=18))
    talking.refresh_from_db()
    assert talking.status == Call.FAILED and any(e["status"] == "finished" for e in talking.events)


@pytest.mark.django_db
def test_outbound_compliance_checks(monkeypatch, line, sara, lead, realty, set_setting):
    FakeTelephony(monkeypatch)
    blocked = services.CallBlocked
    with company_context(realty.id):
        crm.record_consent(lead, "voice", "opt_out", "customer said stop on a call")
        assert ConsentRecord.objects.filter(lead=lead, channel="voice", action="opt_out").exists()
        lead.refresh_from_db()
        assert lead.dnd is True
        with pytest.raises(blocked, match="opted out"):
            services.place_call(sara, lead)
        crm.update_lead(lead, {"dnd": False})
        assert ConsentRecord.objects.filter(lead=lead, action="opt_in").exists()  # every change is recorded
        lead.refresh_from_db()

        set_setting("calling.allowed_country_codes", ["+44"])
        with pytest.raises(blocked, match="country"):
            services.place_call(sara, lead)
        set_setting("calling.allowed_country_codes", ["+91"])

        set_setting("calling.window_start", "09:00")
        set_setting("calling.window_end", "21:00")
        night = timezone.make_aware(dt.datetime(2026, 10, 20, 23, 30), dt.timezone(dt.timedelta(hours=5, minutes=30)))
        with pytest.raises(blocked) as exc:
            services.check_outbound(sara, lead, night)
        assert "between 09:00 and 21:00" in exc.value.messages[0]
        assert timezone.localtime(exc.value.retry_at).strftime("%d %H:%M") == "21 09:00"
        for k, v in WINDOW.items():
            set_setting(k, v)

        services.place_call(sara, lead)
        services.place_call(sara, lead)
        with pytest.raises(blocked, match="maximum number of times today"):
            services.place_call(sara, lead)  # 2 per lead per day (setting)

        other = crm.create_lead(realty, {"name": "Asha", "phone": "+919876500001"})
        realty.plan = Plan.objects.order_by("sort_order").first()
        realty.save()
        PlanEntitlement.objects.update_or_create(plan=realty.plan, key="calls", defaults={"limit_value": 2})
        sara = AIEmployee.objects.select_related("company").get(pk=sara.pk)  # fresh company (plan)
        with pytest.raises(blocked, match="calls this month"):
            services.place_call(sara, other)
        PlanEntitlement.objects.filter(plan=realty.plan, key="calls").delete()

        AIEmployee.objects.filter(pk=sara.pk).update(status=AIEmployee.PAUSED)
        sara.refresh_from_db()
        with pytest.raises(blocked, match="not active"):
            services.place_call(sara, other)


@pytest.mark.django_db
def test_company_can_only_tighten_the_calling_rules(realty, set_setting):
    set_setting("calling.window_start", "09:00")
    set_setting("calling.window_end", "21:00")
    with pytest.raises(Exception, match="platform limit"):
        services.save_policy(realty, {"window_start": "08:00"})
    with pytest.raises(Exception, match="platform limit"):
        services.save_policy(realty, {"max_attempts_per_lead_per_day": 5})
    rules = services.save_policy(realty, {"window_start": "10:00", "window_end": "19:00", "max_attempts_per_lead": 2})
    assert rules["window_start"] == "10:00" and rules["window_end"] == "19:00" and rules["max_attempts_per_lead"] == 2
    set_setting("calling.window_end", "18:00")  # platform tightened later → still wins
    assert services.policy(realty)["window_end"] == "18:00"


# ---------------------------------------------------------------- webhooks (SEC-13) and the state machine
@pytest.mark.django_db
def test_status_webhooks_verify_dedupe_and_finish_the_call(monkeypatch, client, line, sara, lead, realty):
    FakeTelephony(monkeypatch)
    with company_context(realty.id):
        call = services.place_call(sara, lead)
    p = line.provider
    base = {"CallSid": "CA0001", "To": "+919876543210", "From": "+918045678901"}
    bad = client.post(f"/webhooks/telephony/twilio/{'x' * 32}/status/", {**base, "CallStatus": "ringing"})
    assert bad.status_code == 403
    forged = twilio_post(client, p, "status", {**base, "CallStatus": "ringing"}, {"call": call.pk}, secret="wrong")
    assert forged.status_code == 403
    for i, st in enumerate(["ringing", "in-progress"]):
        r = twilio_post(client, p, "status", {**base, "CallStatus": st, "SequenceNumber": str(i)}, {"call": call.pk})
        assert r.status_code == 204
    again = twilio_post(
        client, p, "status", {**base, "CallStatus": "ringing", "SequenceNumber": "0"}, {"call": call.pk}
    )
    assert again.status_code == 204
    done = {**base, "CallStatus": "completed", "CallDuration": "75", "SequenceNumber": "3"}
    twilio_post(client, p, "status", done, {"call": call.pk})
    with company_context(realty.id):
        call.refresh_from_db()
        assert call.status == Call.COMPLETED and call.duration_sec == 75 and call.answered_at and call.ended_at
        assert [e["status"] for e in call.events][:4] == ["queued", "dialled", "ringing", "in_progress"]
        meters = dict(UsageEvent.objects.filter(company=realty).values_list("meter", "quantity"))
        assert meters == {"calls": 1, "voice_minutes_outbound": 2}
        assert LeadActivity.objects.filter(lead=lead, type="call", summary__contains="Completed · 1m 15s").exists()
        lead.refresh_from_db()
        assert lead.last_contact_at
        assert services.transition(call, Call.RINGING) is False  # terminal: no way back
        assert not Call.objects.filter(retry_of=call).exists()  # completed calls are not retried


@pytest.mark.django_db
def test_busy_call_is_retried_by_the_scheduler_within_the_caps(
    monkeypatch, client, line, sara, lead, realty, set_setting
):
    fake = FakeTelephony(monkeypatch)
    with company_context(realty.id):
        call = services.place_call(sara, lead)
    twilio_post(client, line.provider, "status", {"CallSid": "CA0001", "CallStatus": "busy"}, {"call": call.pk})
    with company_context(realty.id):
        retry = Call.objects.get(retry_of=call)
    assert retry.status == Call.QUEUED and retry.attempt == 2 and retry.reason == "retry"
    assert retry.next_retry_at > timezone.now() + dt.timedelta(minutes=59)
    assert services.dial_due() == 0  # not due yet
    assert services.dial_due(retry.next_retry_at + dt.timedelta(seconds=1)) == 1
    retry.refresh_from_db()
    assert retry.provider_call_id == "CA0002" and len(fake.calls) == 2
    # the third attempt is the last one allowed (calling.max_attempts_per_lead = 3)
    twilio_post(client, line.provider, "status", {"CallSid": "CA0002", "CallStatus": "no-answer"}, {"call": retry.pk})
    with company_context(realty.id):
        third = Call.objects.get(retry_of=retry)
    set_setting("calling.window_start", "09:00")
    set_setting("calling.window_end", "09:01")
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    late = (timezone.now() + dt.timedelta(days=1)).astimezone(ist).replace(hour=22, minute=0)  # after the window
    assert services.dial_due(late) == 0
    third.refresh_from_db()
    assert third.status == Call.QUEUED and timezone.localtime(third.next_retry_at).strftime("%H:%M") == "09:00"
    for k, v in WINDOW.items():
        set_setting(k, v)
    services.dial_due(third.next_retry_at)
    twilio_post(client, line.provider, "status", {"CallSid": "CA0003", "CallStatus": "busy"}, {"call": third.pk})
    with company_context(realty.id):
        assert not Call.objects.filter(retry_of=third).exists()


# ---------------------------------------------------------------- answering: inbound routing, voicemail (VOICE-01, 17)
@pytest.mark.django_db
def test_inbound_call_streams_to_the_connected_ai_employee(client, line, sara, lead, realty):
    params = {"CallSid": "CAin1", "From": "+919876543210", "To": "+918045678901", "CallStatus": "ringing"}
    r = twilio_post(client, line.provider, "answer", params)
    body = r.content.decode()
    assert r.status_code == 200 and r["Content-Type"] == "application/xml"
    with company_context(realty.id):
        call = Call.objects.get(provider_call_id="CAin1")
    assert call.direction == "inbound" and call.lead == lead and call.employee == sara and call.status == Call.RINGING
    assert '<Stream url="ws://127.0.0.1:8765/media/twilio">' in body
    assert f'value="{call.pk}"' in body and services.media_token(call.pk) in body

    unrouted = twilio_post(client, line.provider, "answer", {**params, "CallSid": "CAin2", "To": "+918000000000"})
    assert "<Hangup/>" in unrouted.content.decode()
    AIEmployee.all_companies.filter(pk=sara.pk).update(status=AIEmployee.PAUSED)
    paused = twilio_post(client, line.provider, "answer", {**params, "CallSid": "CAin3"})
    assert "<Hangup/>" in paused.content.decode()


@pytest.mark.django_db
def test_voicemail_is_detected_and_handled_by_setting(monkeypatch, client, line, sara, lead, realty, set_setting):
    FakeTelephony(monkeypatch)
    with company_context(realty.id):
        call = services.place_call(sara, lead)
    params = {"CallSid": "CA0001", "CallStatus": "in-progress", "AnsweredBy": "machine_end_beep"}
    r = twilio_post(client, line.provider, "answer", params, {"call": call.pk})
    assert 'name="mode" value="voicemail"' in r.content.decode()
    twilio_post(
        client,
        line.provider,
        "status",
        {"CallSid": "CA0001", "CallStatus": "in-progress", "SequenceNumber": "1"},
        {"call": call.pk},
    )
    twilio_post(
        client,
        line.provider,
        "status",
        {"CallSid": "CA0001", "CallStatus": "completed", "SequenceNumber": "2"},
        {"call": call.pk},
    )
    with company_context(realty.id):
        call.refresh_from_db()
        assert call.status == Call.VOICEMAIL and call.amd_result == "machine"
        assert Call.objects.filter(retry_of=call).exists()  # voicemail is a retry outcome by default
    set_setting("calling.voicemail_action", "hangup")
    with company_context(realty.id):
        Call.objects.filter(retry_of=call).delete()
        second = services.place_call(sara, crm.create_lead(realty, {"name": "B", "phone": "+919876500002"}))
    r = twilio_post(
        client, line.provider, "answer", {**params, "CallSid": second.provider_call_id}, {"call": second.pk}
    )
    assert "<Hangup/>" in r.content.decode()


# ---------------------------------------------------------------- other vendors
@pytest.mark.django_db
def test_plivo_signature_and_events():
    p = Provider.objects.get(key="plivo")
    p.api_key, p.config = "pl-secret", {"auth_id": "MA1"}
    adapter = telephony.for_provider(p)
    url = "https://example.com/webhooks/telephony/plivo/tok/status/?call=1"
    sig = base64.b64encode(
        hmac.new(b"pl-secret", b"https://example.com/webhooks/telephony/plivo/tok/status/n1", hashlib.sha256).digest()
    )
    headers = {"X-Plivo-Signature-V2": sig.decode(), "X-Plivo-Signature-V2-Nonce": "n1"}
    assert adapter.verify(url, {}, headers) and not adapter.verify(
        url, {}, {**headers, "X-Plivo-Signature-V2-Nonce": "n2"}
    )
    event = adapter.parse({"CallUUID": "u1", "CallStatus": "no-answer", "From": "918045678901", "To": "919876543210"})
    assert event["status"] == Call.NO_ANSWER and event["from"] == "+918045678901"
    assert "<Stream" in adapter.answer("wss://gw/media/plivo", {"call": "1", "sig": "s"})
    exotel = Provider.objects.get(key="exotel")
    exotel.config = {"account_sid": "acme", "api_key": "k", "subdomain": "api.in.exotel.com", "flow_id": "42"}
    e = telephony.for_provider(exotel).parse({"CallSid": "x1", "Status": "busy"})
    assert e["status"] == Call.BUSY
    assert (
        urllib.parse.urlparse(
            __import__("json").loads(telephony.for_provider(exotel).answer("wss://gw/media/exotel", {"call": "1"}))[
                "url"
            ]
        ).query
        == "call=1"
    )


# ---------------------------------------------------------------- API, permissions, page
@pytest.mark.django_db
def test_calls_api_call_now_permissions_and_scoping(monkeypatch, line, sara, lead, realty, company_b):
    FakeTelephony(monkeypatch)
    owner = make_user("boss@realty.example")
    add_member(realty, owner.email, Role.objects.get(scope="company", key="owner"))
    c = Client()
    c.force_login(owner)
    r = c.post("/api/v1/calls/", {"lead": str(lead.pk), "employee": str(sara.pk)}, content_type="application/json")
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "queued" and r.json()["lead_name"] == "Ravi"
    assert len(c.get("/api/v1/calls/").json()["results"]) == 1
    detail = c.get(f"/api/v1/calls/{r.json()['id']}/").json()
    assert detail["events"][0]["status"] == "queued" and "summary" in detail
    when = (timezone.now() + dt.timedelta(days=1)).isoformat()
    r = c.post(
        "/api/v1/calls/schedule/", {"lead": str(lead.pk), "employee": str(sara.pk), "at": when}, "application/json"
    )
    assert r.status_code == 201 and r.json()["reason"] == "follow_up"
    assert c.post(f"/api/v1/calls/{r.json()['id']}/cancel/").json()["status"] == "canceled"
    r = c.put("/api/v1/calling-policy/", {"max_calls_per_day": 50}, content_type="application/json")
    assert r.status_code == 200 and r.json()["effective"]["max_calls_per_day"] == 50

    other = make_user("boss@beta.example")
    add_member(company_b, other.email, Role.objects.get(scope="company", key="owner"))
    o = Client()
    o.force_login(other)
    assert o.get("/api/v1/calls/").json()["results"] == []
    assert (
        o.post("/api/v1/calls/", {"lead": str(lead.pk), "employee": str(sara.pk)}, "application/json").status_code
        == 400
    )
    agent = make_user("agent@realty.example")
    add_member(realty, agent.email, Role.objects.get(scope="company", key="agent"))
    a = Client()
    a.force_login(agent)
    assert a.get("/api/v1/calls/").status_code == 200
    assert a.patch(f"/api/v1/phone-numbers/{line.pk}/", {"employee": None}, "application/json").status_code == 403


@pytest.mark.django_db
def test_phone_numbers_page_renders(admin_client, line):
    html = admin_client.get("/superadmin/phone-numbers/").content.decode()
    assert "Phone Numbers" in html and "+918045678901" in html and "/webhooks/telephony/twilio/" in html
