"""Phase 6 part 2: WhatsApp (WA-01 … WA-10, TOOL-09, COMP-07, SEC-13). Meta's API and the LLM are faked."""

import datetime as dt
import hashlib
import hmac
import json

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from apps.agents import inbox, runtime
from apps.agents import services as employees
from apps.agents import tools as toolkit
from apps.agents.models import AIEmployee, Conversation, UsageEvent
from apps.catalog.models import CatalogItem, CatalogMedia
from apps.crm import services as crm
from apps.crm.models import ConsentRecord, Lead
from apps.industries.models import CatalogType, Industry
from apps.providers.models import Provider
from apps.tenancy.context import company_context
from apps.whatsapp import cloud
from apps.whatsapp import services as wa
from apps.whatsapp.models import DefaultTemplate, Template, WaMessage

from .test_ai_engine import FakeLLM
from .test_voice_handoff import agent

SECRET = "app-secret"  # noqa: S105 — test value


class FakeMeta:
    """Records what would be sent to Meta and returns message ids."""

    def __init__(self, monkeypatch):
        self.sent, self.read, self.uploads, self.n = [], [], [], 0
        self.remote_templates = []
        for name in (
            "send_text",
            "send_media",
            "send_location",
            "send_template",
            "mark_read",
            "upload_media",
            "download_media",
            "create_template",
            "list_templates",
            "upload_example",
        ):
            fn = getattr(self, "_" + name)
            monkeypatch.setattr(cloud.MetaCloud, name, lambda adapter, *a, fn=fn, **k: fn(adapter, *a, **k))

    def _id(self):
        self.n += 1
        return f"wamid.{self.n}"

    def _send_text(self, _self, number, to, text):
        self.sent.append(("text", to, text))
        return self._id()

    def _send_media(self, _self, number, to, kind, media_id, caption="", filename=""):
        self.sent.append((kind, to, media_id))
        return self._id()

    def _send_location(self, _self, number, to, lat, lng, name="", address=""):
        self.sent.append(("location", to, (lat, lng)))
        return self._id()

    def _send_template(self, _self, number, to, template, params, header_media_id=""):
        self.sent.append(("template", to, template.name, list(params), header_media_id))
        return self._id()

    def _mark_read(self, _self, number, wamid):
        self.read.append(wamid)

    def _upload_media(self, _self, number, content, mime, filename):
        self.uploads.append(filename)
        return f"media-{len(self.uploads)}"

    def _download_media(self, _self, media_id):
        return b"OggS-fake-audio", "audio/ogg; codecs=opus"

    def _create_template(self, _self, template, handle=""):
        return "tpl-123", "pending"

    def _list_templates(self, _self, waba):
        return self.remote_templates

    def _upload_example(self, _self, content, mime):
        return "handle-1"

    def texts(self):
        return [s[2] for s in self.sent if s[0] == "text"]


@pytest.fixture
def realty(company_a, set_setting):
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
def meta(db):
    p = Provider.objects.get(key="meta-whatsapp")
    p.api_key, p.webhook_secret, p.is_active = "EAAtoken", SECRET, True
    p.save()
    return p


@pytest.fixture
def number(meta, realty, sara):
    n = wa.save_number(
        None,
        {
            "provider": "meta-whatsapp",
            "e164": "+919000000001",
            "phone_number_id": "PNID1",
            "waba_id": "WABA1",
            "company": str(realty.pk),
        },
    )
    with company_context(realty.id):
        wa.connect_number(realty, n, sara)
    return n


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(wa, "RUN_INLINE", True)
    return FakeMeta(monkeypatch)


def payload(phone_id="PNID1", messages=(), statuses=(), name="Ravi"):
    value = {"metadata": {"phone_number_id": phone_id}, "messaging_product": "whatsapp"}
    if messages:
        value["messages"] = list(messages)
        value["contacts"] = [{"wa_id": m["from"], "profile": {"name": name}} for m in messages]
    if statuses:
        value["statuses"] = list(statuses)
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": value}]}]}


def text_msg(body, wamid="wamid.in1", sender="919876543210"):
    return {"from": sender, "id": wamid, "type": "text", "text": {"body": body}, "timestamp": "1"}


def post(client, data, secret=SECRET):
    body = json.dumps(data).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/whatsapp/meta-whatsapp/", body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=sig
    )


# ---------------------------------------------------------------- SEC-13 webhook
@pytest.mark.django_db
def test_webhook_verification_and_signature(meta, fake):
    c = Client()
    token = wa.webhook_token(meta)
    ok = c.get(
        "/webhooks/whatsapp/meta-whatsapp/", {"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "42"}
    )
    assert ok.status_code == 200 and ok.content == b"42"
    bad = c.get(
        "/webhooks/whatsapp/meta-whatsapp/", {"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"}
    )
    assert bad.status_code == 403
    assert post(c, payload(), secret="wrong").status_code == 403
    assert post(c, payload()).status_code == 200
    assert c.get("/webhooks/whatsapp/unknown/").status_code == 404


# ---------------------------------------------------------------- WA-05 AI replies, opt-in, lead
@pytest.mark.django_db
def test_customer_message_gets_disclosure_then_ai_answer(number, fake, realty, monkeypatch):
    llm = FakeLLM(monkeypatch, [{"text": "Hello Ravi! Which area are you looking in?"}])
    assert post(Client(), payload(messages=[text_msg("Hi, need a 2 BHK")])).status_code == 200
    texts = fake.texts()
    assert len(texts) == 2 and "AI" in texts[0] and texts[1] == "Hello Ravi! Which area are you looking in?"
    assert fake.read == ["wamid.in1"] and llm.calls[0]["task"] == "chat_dialog"
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="whatsapp")
        assert conv.customer["phone"] == "+919876543210" and conv.customer["name"] == "Ravi"
        lead = Lead.objects.get(phone="+919876543210")
        assert conv.lead == lead and lead.source.key == "whatsapp" and wa.consent_state(lead) == "opted_in"
        rows = WaMessage.objects.order_by("created_at")
        assert [r.direction for r in rows] == ["in", "out", "out"] and rows[0].message.content == "Hi, need a 2 BHK"
    # Meta retries the same message: processed once
    post(Client(), payload(messages=[text_msg("Hi, need a 2 BHK")]))
    assert len(fake.texts()) == 2
    # the next message continues the same conversation
    FakeLLM(monkeypatch, [{"text": "Noted."}])
    post(Client(), payload(messages=[text_msg("New Town", wamid="wamid.in2")]))
    with company_context(realty.id):
        assert Conversation.objects.filter(channel="whatsapp").count() == 1
    assert fake.texts()[-1] == "Noted."


@pytest.mark.django_db
def test_opt_out_keyword_is_honoured_and_blocks_templates(number, fake, realty, monkeypatch):
    llm = FakeLLM(monkeypatch, [])
    post(Client(), payload(messages=[text_msg("stop")]))
    assert len(llm.calls) == 0 and "START" in fake.texts()[-1]
    with company_context(realty.id):
        lead = Lead.objects.get(phone="+919876543210")
        assert wa.consent_state(lead) == "opted_out"
        assert ConsentRecord.objects.filter(lead=lead, channel="whatsapp", action="opt_out", source="whatsapp_keyword")
        with pytest.raises(ValidationError, match="opted out"):
            wa.check_can_message(lead)
    post(Client(), payload(messages=[text_msg("START", wamid="wamid.in2")]))
    with company_context(realty.id):
        assert wa.consent_state(lead) == "opted_in"


@pytest.mark.django_db
def test_voice_note_is_transcribed_and_answered(number, fake, realty, monkeypatch):
    from apps.providers import transcribe

    monkeypatch.setattr(transcribe, "transcribe", lambda audio, mime, lang: ("mujhe 2 BHK chahiye", "sarvam"))
    FakeLLM(monkeypatch, [{"text": "Zaroor! Kaunsa area?"}])
    msg = {"from": "919876543210", "id": "wamid.v1", "type": "audio", "audio": {"id": "MEDIA1", "voice": True}}
    post(Client(), payload(messages=[msg]))
    assert fake.texts()[-1] == "Zaroor! Kaunsa area?"
    with company_context(realty.id):
        stored = Conversation.objects.get(channel="whatsapp").messages.get(role="customer")
        assert (
            stored.content == "mujhe 2 BHK chahiye"
            and stored.meta["voice_note"] is True
            and stored.meta["stt"] == "sarvam"
        )


# ---------------------------------------------------------------- WA-10 delivery tracking and usage
@pytest.mark.django_db
def test_status_updates_move_forward_and_meter_usage_once(number, fake, realty, monkeypatch):
    FakeLLM(monkeypatch, [{"text": "Hi!"}])
    post(Client(), payload(messages=[text_msg("hello")]))
    with company_context(realty.id):
        out = WaMessage.objects.filter(direction="out").order_by("created_at").last()
    pricing = {"billable": False, "category": "service", "pricing_model": "PMP"}
    for st in ("delivered", "read", "delivered"):
        post(Client(), payload(statuses=[{"id": out.wamid, "status": st, "pricing": pricing}]))
    with company_context(realty.id):
        out.refresh_from_db()
        assert out.status == "read" and out.category == "service" and out.billable is False
        assert UsageEvent.objects.filter(meter="whatsapp_messages").count() == 1
    post(Client(), payload(statuses=[{"id": out.wamid, "status": "failed", "errors": [{"title": "Re-engagement"}]}]))
    with company_context(realty.id):
        out.refresh_from_db()
        assert out.status == "failed" and out.error == "Re-engagement"


# ---------------------------------------------------------------- WA-06 / WA-07 inbox and the 24-hour window
@pytest.mark.django_db
def test_team_takes_over_on_whatsapp_and_window_rules(number, fake, realty, monkeypatch, set_setting):
    asha = agent(realty, "asha@alpha.example")
    FakeLLM(monkeypatch, [{"text": "Hi!"}])
    post(Client(), payload(messages=[text_msg("hello")]))
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="whatsapp")
    team = Client()
    team.force_login(asha)
    r = team.post(
        f"/api/v1/inbox/{conv.pk}/reply/", {"text": "Asha here, how can I help?"}, content_type="application/json"
    )
    assert r.status_code == 200 and r.json()["window_open"] is True
    assert fake.texts()[-1] == "Asha here, how can I help?"
    assert any("Asha" in t for t in fake.texts())  # "Asha from our team has joined" sent too
    # customer writes while a person handles the chat: the AI stays quiet
    llm = FakeLLM(monkeypatch, [])
    post(Client(), payload(messages=[text_msg("parking?", wamid="wamid.in2")]))
    assert llm.calls == []
    # window closed → free text refused, approved template allowed
    with company_context(realty.id):
        WaMessage.objects.filter(direction="in").update(created_at=timezone.now() - dt.timedelta(hours=30))
    r = team.post(f"/api/v1/inbox/{conv.pk}/reply/", {"text": "still there?"}, content_type="application/json")
    assert r.status_code == 400 and "24-hour" in r.json()["error"]["details"][0]
    with company_context(realty.id):
        t = _approved(realty, number, "lead_follow_up", ["lead.name", "company.name"])
    r = team.post(f"/api/v1/inbox/{conv.pk}/template/", {"template": str(t.pk)}, content_type="application/json")
    assert r.status_code == 200, r.content
    assert fake.sent[-1][0] == "template" and fake.sent[-1][3] == ["Ravi", realty.name]
    assert r.json()["messages"][-1]["template"] == "lead_follow_up"


def _approved(company, number, purpose, variables, header="none", name=None):
    body = " ".join(f"{{{{{i + 1}}}}}" for i in range(len(variables))) or "Hello"
    t = wa.save_template(
        company,
        None,
        {
            "number": number.pk,
            "name": name or purpose,
            "language": "en",
            "category": "UTILITY",
            "purpose": purpose,
            "header_type": header,
            "body": f"Hi {body}",
            "variables": variables,
        },
    )
    Template.objects.filter(pk=t.pk).update(status=Template.APPROVED)
    t.refresh_from_db()
    return t


# ---------------------------------------------------------------- WA-03 templates
@pytest.mark.django_db
def test_template_rules_library_submit_and_sync(number, fake, realty):
    with company_context(realty.id):
        for bad in ({"name": "Bad Name"}, {"body": "Hi {{1}} and {{3}}"}, {"variables": ["nonsense"]}):
            data = {
                "number": number.pk,
                "name": "ok_name",
                "language": "en",
                "category": "UTILITY",
                "purpose": "general",
                "body": "Hi {{1}}",
                "variables": ["lead.name"],
                **bad,
            }
            with pytest.raises(ValidationError):
                wa.save_template(realty, None, data)
        default = DefaultTemplate.objects.get(name="appointment_confirmation")
        t = wa.copy_default(realty, default, number, "hi")
        assert t.status == "draft" and "{{4}}" in t.body and t.variables[2] == "appointment.when"
        t = wa.submit_template(t)
        assert t.status == "pending" and t.provider_template_id == "tpl-123"
        with pytest.raises(ValidationError):
            wa.save_template(realty, t, {"body": "changed"})  # submitted templates are locked
        fake.remote_templates = [{"name": t.name, "language": "hi", "status": "APPROVED", "id": "tpl-123"}]
        assert wa.sync_templates(realty) == 1
        t.refresh_from_db()
        assert t.status == "approved"
        img = wa.copy_default(realty, DefaultTemplate.objects.get(name="item_details"), number, "en")
        with pytest.raises(ValidationError, match="sample"):
            wa.submit_template(img)
        assert wa.submit_template(img, (b"jpg", "image/jpeg")).status == "pending"


@pytest.mark.django_db
def test_sending_templates_checks_consent_values_and_media(number, fake, realty, set_setting):
    with company_context(realty.id):
        lead = crm.create_lead(realty, {"name": "Meera", "phone": "+919123456780"})
        t = _approved(realty, number, "lead_follow_up", ["lead.name", "company.name"])
        with pytest.raises(ValidationError, match="not opted in"):
            wa.send_template(t, lead)
        set_setting("whatsapp.require_opt_in", False)
        row = wa.send_template(t, lead)
        assert row.status == "sent" and fake.sent[-1][3] == ["Meera", realty.name]
        assert wa.preview(t, ["Meera", realty.name]) == f"Hi Meera {realty.name}"
        # an image header needs an item with a photo
        ctype = CatalogType.objects.filter(template_version=realty.template_version).first()
        item = CatalogItem.objects.create(
            company=realty, catalog_type=ctype, title="Green Valley", price_paise=650000000
        )
        photo_t = _approved(
            realty, number, "item_info", ["lead.name", "item.title", "item.price"], "image", "item_details"
        )
        with pytest.raises(ValidationError, match="photo"):
            wa.send_template(photo_t, lead, {"item": item})
        CatalogMedia.objects.create(company=realty, item=item, kind="photo", file_key="k.jpg", file_name="front.jpg")
        import apps.whatsapp.services as svc

        svc_media = svc._media_bytes
        svc._media_bytes = lambda m: b"jpg"
        try:
            wa.send_template(photo_t, lead, {"item": item})
        finally:
            svc._media_bytes = svc_media
        assert fake.sent[-1][2] == "item_details" and fake.sent[-1][4] == "media-1"
        assert fake.sent[-1][3][1:] == ["Green Valley", "₹65,00,000"]


# ---------------------------------------------------------------- TOOL-09 and the follow-up after a call (WA-04)
@pytest.mark.django_db
def test_send_whatsapp_tool_and_follow_up_after_call(number, fake, realty, sara, set_setting, monkeypatch):
    set_setting("whatsapp.require_opt_in", False)
    with company_context(realty.id):
        t = _approved(realty, number, "lead_follow_up", ["lead.name", "company.name"])
        lead = crm.create_lead(realty, {"name": "Ravi", "phone": "+919876543210"})
        conv = runtime.start(sara, "voice", {"phone": lead.phone}, lead=lead)
        conv.state = {**conv.state, "voice": True}
        conv.save()
        ctx = toolkit.ToolContext(realty, sara, conv, lead=lead)
        tools = toolkit.enabled(sara)
        assert "send_whatsapp" in [d["name"] for d in toolkit.definitions(ctx, tools)]
        out = toolkit.run(ctx, tools, "send_whatsapp", {}, "c1")
        assert out["sent"] is True and out["template"] == t.name
        # rule: WhatsApp follow-up after a call
        AIEmployee.objects.filter(pk=sara.pk).update(rules={**sara.rules, "whatsapp_after_call": True})
        conv.employee.refresh_from_db()
        FakeLLM(monkeypatch, [], analysis={"summary": {"summary": "x", "confidence": 1}})
        before = len([s for s in fake.sent if s[0] == "template"])
        runtime.end(conv)
        assert len([s for s in fake.sent if s[0] == "template"]) == before + 1


# ---------------------------------------------------------------- panels, API, isolation
@pytest.mark.django_db
def test_company_and_admin_pages_and_api(number, fake, realty, owner_a, owner_b, admin_client, monkeypatch):
    c = Client()
    c.force_login(owner_a)
    page = c.get("/app/settings/whatsapp/")
    assert page.status_code == 200 and b"+919000000001" in page.content and b"Template library" in page.content
    default = DefaultTemplate.objects.get(name="lead_follow_up")
    r = c.post(
        "/app/settings/whatsapp/", {"op": "library", "default": default.pk, "number": number.pk, "language": "en"}
    )
    assert r.status_code == 302
    with company_context(realty.id):
        t = Template.objects.get()
    assert c.get(f"/app/settings/whatsapp/templates/{t.pk}/").status_code == 200
    assert c.get("/app/settings/whatsapp/templates/new/").status_code == 200
    with company_context(realty.id):
        lead = crm.create_lead(realty, {"name": "Meera", "phone": "+919123456780"})
    lead_page = c.get(f"/app/leads/{lead.pk}/")
    assert lead_page.status_code == 200 and b"WhatsApp" in lead_page.content
    # API
    assert c.get("/api/v1/whatsapp/numbers/").json()[0]["e164"] == "+919000000001"
    assert len(c.get("/api/v1/whatsapp/templates/").json()["results"]) == 1
    assert c.get("/api/v1/whatsapp/templates/library/").status_code == 200
    other = Client()
    other.force_login(owner_b)
    assert other.get("/api/v1/whatsapp/templates/").json()["results"] == []
    assert other.get("/api/v1/whatsapp/numbers/").json() == []
    r = other.patch(f"/api/v1/whatsapp/numbers/{number.pk}/", {"employee": ""}, content_type="application/json")
    assert r.status_code == 400
    # Super Admin
    assert admin_client.get("/superadmin/whatsapp/numbers/").status_code == 200
    assert b"PNID1" in admin_client.get("/superadmin/whatsapp/numbers/").content
    assert admin_client.get("/superadmin/whatsapp/templates/").status_code == 200
    assert admin_client.get(f"/superadmin/whatsapp/templates/{default.pk}/").status_code == 200
    # inbox shows WhatsApp chats
    FakeLLM(monkeypatch, [{"text": "Hi!"}])
    post(Client(), payload(messages=[text_msg("hello")]))
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="whatsapp")
    assert c.get("/api/v1/inbox/?channel=whatsapp").json()["results"][0]["id"] == str(conv.pk)
    assert c.get(f"/app/inbox/{conv.pk}/").status_code == 200
    with company_context(realty.id):
        assert {x["key"]: x["ok"] for x in employees.readiness(conv.employee)}["channel"] is True


@pytest.mark.django_db
def test_unconnected_number_and_paused_employee(number, fake, realty, sara, monkeypatch):
    llm = FakeLLM(monkeypatch, [])
    post(Client(), payload(phone_id="UNKNOWN", messages=[text_msg("hi")]))
    assert fake.sent == []
    AIEmployee.all_companies.filter(pk=sara.pk).update(status=AIEmployee.PAUSED)
    post(Client(), payload(messages=[text_msg("hi", wamid="wamid.in9")]))
    assert llm.calls == [] and fake.sent == []
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="whatsapp")
        assert conv.handled_by == "waiting" and conv.messages.get(role="customer").content == "hi"
    assert inbox  # the team answers it from the inbox
