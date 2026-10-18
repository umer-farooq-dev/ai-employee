"""Phase 5 part 4: transfer & human handoff (TOOL-08, VOICE-11, HO-01 … HO-05), recording access and retention
(VOICE-12, REC-03, COMP-06). Telephony and the LLM are faked."""

import base64
import datetime as dt
import hashlib
import hmac

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import Client
from django.utils import timezone

from apps.agents import runtime
from apps.agents import services as employees
from apps.agents import tools as toolkit
from apps.agents.models import AIEmployee, Conversation, Message
from apps.audit.models import AuditLog
from apps.core.crypto import encrypt_bytes
from apps.core.storage import private_storage
from apps.crm import services as crm
from apps.crm.models import Lead
from apps.industries.models import Industry
from apps.providers.models import Provider
from apps.rbac.models import Role
from apps.scheduling import services as calendar
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member
from apps.voice import handoff, services
from apps.voice.models import Call, Handoff

from .conftest import make_user
from .test_ai_engine import FakeLLM
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


def agent(company, email, role="agent", availability="online", phone="+919800000001"):
    user = make_user(email)
    user.availability, user.phone, user.full_name = availability, phone, email.split("@")[0].title()
    user.save()
    add_member(company, email, Role.objects.get(scope="company", key=role))
    return user


@pytest.fixture
def twilio(db):
    p = Provider.objects.get(key="twilio")
    p.api_key, p.config, p.is_active = "tw-secret", {"account_sid": "AC1"}, True
    p.save()
    return p


@pytest.fixture
def live_call(monkeypatch, twilio, realty, sara):
    """An answered inbound call with its voice conversation."""
    number = services.save_number(None, {"provider": "twilio", "e164": "+918045678901", "company": str(realty.pk)})
    with company_context(realty.id):
        services.connect_number(realty, number, sara)
        lead = crm.create_lead(realty, {"name": "Ravi", "phone": "+919876543210"})
        call = Call.objects.create(
            company=realty,
            employee=sara,
            lead=lead,
            phone_number=number,
            provider=twilio,
            provider_call_id="CAx",
            direction="inbound",
            from_e164=lead.phone,
            to_e164=number.e164,
            status=Call.IN_PROGRESS,
        )
        conv = runtime.start(sara, "voice", {"phone": lead.phone}, lead=lead)
        conv.state = {**conv.state, "voice": True}
        conv.save()
        call.conversation = conv
        call.save()
    return call


def signed_post(client, provider, action, params, query):
    url = services.webhook_url(provider, action, **query)
    signed = url + "".join(k + str(params[k]) for k in sorted(params))
    sig = base64.b64encode(hmac.new(b"tw-secret", signed.encode(), hashlib.sha1).digest()).decode()
    return client.post(url.replace("http://127.0.0.1:8000", ""), params, HTTP_X_TWILIO_SIGNATURE=sig)


# ---------------------------------------------------------------- TOOL-08 transfer_call
@pytest.mark.django_db
def test_transfer_tool_is_offered_on_calls_only(live_call, sara, realty, monkeypatch):
    with company_context(realty.id):
        conv = live_call.conversation
        tools = toolkit.enabled(sara)
        names = [d["name"] for d in toolkit.definitions(toolkit.ToolContext(realty, sara, conv), tools)]
        assert "transfer_call" in names
        chat = runtime.start(sara, "test", {})
        assert "transfer_call" not in [
            d["name"] for d in toolkit.definitions(toolkit.ToolContext(realty, sara, chat), tools)
        ]
        FakeLLM(
            monkeypatch,
            [{"calls": [("transfer_call", {"reason": "wants to talk to a manager"})]}, {"text": "Connecting you now."}],
        )
        msg = runtime.reply(conv, "Please connect me to your manager")
        conv.refresh_from_db()
    assert msg.content == "Connecting you now."
    assert conv.state["transfer"] == {"reason": "customer_request", "detail": "wants to talk to a manager"}


# ---------------------------------------------------------------- HO-02 routing
@pytest.mark.django_db
def test_routing_order_and_availability(live_call, sara, realty):
    asha = agent(realty, "asha@realty.example")
    bina = agent(realty, "bina@realty.example")
    chetan = agent(realty, "chetan@realty.example")
    agent(realty, "away@realty.example", availability="away")
    agent(realty, "nophone@realty.example", phone="")
    with company_context(realty.id):
        lead = live_call.lead
        crm.assign(lead, chetan)
        employees.update_employee(sara, {"rules": {"transfer_user_ids": [str(bina.pk), str(asha.pk)]}})
        sara.refresh_from_db()
        lead.refresh_from_db()
        order = handoff.route(realty, sara, lead, "voice")
        assert order[:3] == [str(chetan.pk), str(bina.pk), str(asha.pk)]  # assigned → team → anyone (max 3)
        # chetan is in a site visit right now → skipped
        resource = calendar.save_resource(
            realty,
            {
                "name": "Chetan",
                "user": chetan.pk,
                "working_hours": {d: "00:00-23:59" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
            },
        )
        from apps.industries.models import AppointmentType
        from apps.scheduling.models import Appointment

        Appointment.objects.create(
            company=realty,
            number=1,
            resource=resource,
            appointment_type=AppointmentType.objects.first(),
            assigned_user=chetan,
            starts_at=timezone.now() - dt.timedelta(minutes=10),
            ends_at=timezone.now() + dt.timedelta(minutes=20),
        )
        assert str(chetan.pk) not in handoff.route(realty, sara, lead, "voice")


# ---------------------------------------------------------------- HO-01 … HO-05 request, no agent, log
@pytest.mark.django_db
def test_handoff_rings_an_agent_and_alerts_by_email(live_call, sara, realty):
    asha = agent(realty, "asha@realty.example")
    with company_context(realty.id):
        h = handoff.request(live_call.conversation, "customer_request", "wants a person", call=live_call)
        assert h.status == Handoff.RINGING and h.assigned_user == asha and h.mode == "warm"
        assert "Ravi" in h.summary and "Customer asked for a person" in h.summary
        live_call.refresh_from_db()
        assert live_call.transfer_status == "requested"
        assert live_call.lead.activities.filter(type="handoff").exists()
    assert mail.outbox and "Live handoff from Sara" in mail.outbox[-1].subject and "Ravi" in mail.outbox[-1].body


@pytest.mark.django_db
def test_no_agent_creates_a_callback_and_flags_the_lead(live_call, sara, realty):
    agent(realty, "away@realty.example", availability="away")
    with company_context(realty.id):
        h = handoff.request(live_call.conversation, "knowledge_gap", call=live_call)
        assert h.status == Handoff.NO_AGENT and h.callback_task.type == "callback"
        lead = Lead.objects.get(pk=live_call.lead_id)
        assert "no agent was free" in lead.next_action
        assert Call.objects.get(pk=live_call.pk).transfer_status == "no_agent"
    out = handoff.start_transfer(str(live_call.pk), "customer_request")
    assert out["status"] == "no_agent" and out["end"] is False


# ---------------------------------------------------------------- VOICE-11 warm transfer through the webhooks
@pytest.mark.django_db
def test_warm_transfer_dials_whispers_and_falls_back_to_the_next_agent(client, live_call, sara, realty):
    asha = agent(realty, "asha@realty.example", phone="+919800000001")
    bina = agent(realty, "bina@realty.example", phone="+919800000002")
    out = handoff.start_transfer(str(live_call.pk), "customer_request", "manager please")
    assert out["status"] == "ringing" and "/transfer/?handoff=" in out["transfer_url"]
    live_call.refresh_from_db()
    assert live_call.status == Call.TRANSFERRING
    h = Handoff.all_companies.get(pk=out["handoff"])
    first = asha if h.assigned_user_id == asha.pk else bina
    second = bina if first == asha else asha

    r = signed_post(client, live_call.provider, "transfer", {"CallSid": "CAx"}, {"handoff": h.pk})
    xml = r.content.decode()
    assert (
        "<Number url=" in xml and first.phone in xml and 'callerId="+918045678901"' in xml and "transfer-result" in xml
    )
    # the first agent does not answer → the second one is dialled
    r = signed_post(
        client,
        live_call.provider,
        "transfer-result",
        {"CallSid": "CAx", "DialCallStatus": "no-answer"},
        {"handoff": h.pk},
    )
    assert second.phone in r.content.decode()
    # the second agent picks up: the whisper plays the summary and marks the handoff accepted
    r = signed_post(client, live_call.provider, "whisper", {"CallSid": "CAy"}, {"handoff": h.pk})
    assert "<Say>" in r.content.decode() and "Ravi" in r.content.decode()
    h.refresh_from_db()
    assert h.status == Handoff.ACCEPTED and h.assigned_user == second and h.seconds_to_answer is not None
    live_call.refresh_from_db()
    assert live_call.status == Call.TRANSFERRED and live_call.transfer_status == "completed"
    signed_post(
        client,
        live_call.provider,
        "transfer-result",
        {"CallSid": "CAx", "DialCallStatus": "completed"},
        {"handoff": h.pk},
    )
    h.refresh_from_db()
    assert h.status == Handoff.COMPLETED and h.tried_user_ids == [str(first.pk), str(second.pk)]


@pytest.mark.django_db
def test_redirect_moves_the_live_call_and_a_failure_keeps_the_ai(monkeypatch, live_call, sara, realty):
    agent(realty, "asha@realty.example")
    fake = FakeTelephony(monkeypatch)
    out = handoff.start_transfer(str(live_call.pk), "customer_request")
    assert handoff.redirect(str(live_call.pk), out["transfer_url"]) is True
    assert fake.calls[-1]["url"].endswith("/Calls/CAx.json") and fake.calls[-1]["data"]["Url"] == out["transfer_url"]
    FakeTelephony(monkeypatch, fail=True)
    assert handoff.redirect(str(live_call.pk), out["transfer_url"]) is False
    live_call.refresh_from_db()
    assert live_call.status == Call.IN_PROGRESS and live_call.transfer_status == "failed"


@pytest.mark.django_db
def test_browser_test_transfer_is_simulated_but_alerts_the_agent(sara, realty):
    agent(realty, "asha@realty.example")
    with company_context(realty.id):
        call = Call.objects.create(
            company=realty, employee=sara, direction="outbound", reason="browser_test", status=Call.IN_PROGRESS
        )
        call.conversation = runtime.start(sara, "test", {})
        call.save()
    out = handoff.start_transfer(str(call.pk), "customer_request")
    assert out["status"] == "simulated" and out["end"] is True and mail.outbox


# ---------------------------------------------------------------- HO-01 configurable triggers
@pytest.mark.django_db
def test_rule_triggers_on_calls(monkeypatch, live_call, sara, realty, set_setting):
    with company_context(realty.id):
        employees.update_employee(sara, {"rules": {"handoff_keywords": ["complaint", "manager"]}})
        conv = live_call.conversation
        FakeLLM(monkeypatch, [{"text": "I understand."}])
        runtime.reply(conv, "I want to make a complaint")
        conv.refresh_from_db()
        assert conv.state["transfer"]["reason"] == "keyword"

        conv.state = {**conv.state, "transfer": None}
        conv.save()
        set_setting("handoff.repeat_failures", 2)
        FakeLLM(
            monkeypatch,
            [
                {"calls": [("cannot_answer", {"question": "pool?"})]},
                {"calls": [("cannot_answer", {"question": "gym?"})]},
            ],
        )
        runtime.reply(conv, "Is there a pool?")
        conv.refresh_from_db()
        assert not conv.state.get("transfer")
        runtime.reply(conv, "Is there a gym?")
        conv.refresh_from_db()
        assert conv.state["transfer"]["reason"] == "repeated_failure"

        chat = runtime.start(sara, "test", {})  # text chats are not transferred (Phase 6 inbox)
        FakeLLM(monkeypatch, [{"text": "Sure."}])
        runtime.reply(chat, "manager please")
        chat.refresh_from_db()
        assert not chat.state.get("transfer")

        # negative sentiment: the instruction is added only when the rule is on; the AI hands over with "upset …"
        conv.state = {**conv.state, "transfer": None}
        conv.save()
        fake = FakeLLM(monkeypatch, [{"text": "Okay."}])
        runtime.reply(conv, "hello")
        assert "upset" not in fake.calls[0]["messages"][0]["content"]
        employees.update_employee(sara, {"rules": {**sara.rules, "handoff_on_upset": True}})
        conv = Conversation.objects.get(pk=conv.pk)  # fresh employee, as on the next call turn
        fake = FakeLLM(
            monkeypatch,
            [{"calls": [("transfer_call", {"reason": "upset about the delay"})]}, {"text": "Sorry, connecting you."}],
        )
        runtime.reply(conv, "This is useless, I have waited three weeks!")
        conv.refresh_from_db()
        assert "angry, upset or frustrated" in fake.calls[0]["messages"][0]["content"]
        assert conv.state["transfer"]["reason"] == "negative_sentiment"


# ---------------------------------------------------------------- HO-03 screen pop API
@pytest.mark.django_db
def test_screen_pop_and_accept(live_call, sara, realty):
    asha = agent(realty, "asha@realty.example")
    other = agent(realty, "zed@realty.example", availability="offline")
    with company_context(realty.id):
        h = handoff.request(live_call.conversation, "customer_request", call=live_call)
    c = Client()
    c.force_login(asha)
    rows = c.get("/api/v1/handoffs/live/").json()
    assert rows[0]["id"] == str(h.pk) and rows[0]["lead_name"] == "Ravi" and rows[0]["reason_label"]
    html = c.get("/app/").content.decode()
    assert "Receive live handoffs" in html and "handoffs/live/" in html
    o = Client()
    o.force_login(other)
    assert o.get("/api/v1/handoffs/live/").json() == []
    assert o.post(f"/api/v1/handoffs/{h.pk}/accept/").status_code == 400
    assert c.post(f"/api/v1/handoffs/{h.pk}/accept/").json()["status"] == "accepted"
    owner = agent(realty, "boss@realty.example", role="owner")
    b = Client()
    b.force_login(owner)
    assert b.get("/api/v1/handoffs/").json()["results"][0]["seconds_to_answer"] is not None


# ---------------------------------------------------------------- VOICE-12 / REC-03 recording access + retention
@pytest.fixture
def recorded(tmp_path, monkeypatch, live_call, realty):
    monkeypatch.setattr(private_storage, "_wrapped", FileSystemStorage(location=tmp_path))
    key = f"tenants/{realty.id}/recordings/x.wav.enc"
    private_storage.save(key, ContentFile(encrypt_bytes(b"RIFF....WAVEfmt fake")))
    with company_context(realty.id):
        Call.objects.filter(pk=live_call.pk).update(
            recording_key=key,
            recording_status="stored",
            status=Call.COMPLETED,
            ended_at=timezone.now() - dt.timedelta(days=100),
        )
    return live_call


@pytest.mark.django_db
def test_recording_listen_and_download_follow_permissions_and_are_audited(recorded, realty):
    agent_user = agent(realty, "asha@realty.example")  # agents may listen, not download
    c = Client()
    c.force_login(agent_user)
    r = c.get(f"/api/v1/calls/{recorded.pk}/recording/")
    assert r.status_code == 200
    audio = c.get(r.json()["url"])
    assert audio["Content-Type"] == "audio/wav" and audio["Content-Disposition"].startswith("inline")
    assert b"".join(audio.streaming_content if audio.streaming else [audio.content]).startswith(b"RIFF")
    assert c.get(f"/api/v1/calls/{recorded.pk}/recording/?download=1").status_code == 403
    owner = agent(realty, "boss@realty.example", role="owner")
    o = Client()
    o.force_login(owner)
    dl = o.get(o.get(f"/api/v1/calls/{recorded.pk}/recording/?download=1").json()["url"])
    assert dl["Content-Disposition"].startswith("attachment")
    actions = list(AuditLog.objects.filter(entity_id=str(recorded.pk)).values_list("action", flat=True))
    assert "recording.listen" in actions and "recording.download" in actions
    assert Client().get("/calls/recording/forged-token/").status_code == 404


@pytest.mark.django_db
def test_retention_removes_old_recordings_and_transcripts(recorded, realty):
    with company_context(realty.id):
        Conversation.objects.filter(pk=recorded.conversation_id).update(
            ended_at=timezone.now() - dt.timedelta(days=400)
        )
        assert Message.objects.filter(conversation_id=recorded.conversation_id).exists()
    removed = services.apply_retention()
    assert removed["recordings"] == 1 and removed["transcripts"] >= 1
    with company_context(realty.id):
        call = Call.objects.get(pk=recorded.pk)
        assert call.recording_status == "deleted" and call.recording_key == ""
        assert not Message.objects.filter(conversation_id=recorded.conversation_id).exists()
        assert Conversation.objects.filter(pk=recorded.conversation_id).exists()  # summary / fields stay
