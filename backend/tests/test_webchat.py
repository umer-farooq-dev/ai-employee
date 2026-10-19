"""Phase 6 part 1: website chat widget (CHAT-01 … CHAT-07), shared inbox and chat handoff (WA-06 base, CHAT-06,
HO-01 chat, REC-02). The LLM is faked."""

import datetime as dt

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from apps.agents import inbox
from apps.agents import services as employees
from apps.agents import tools as toolkit
from apps.agents.models import AIEmployee, Conversation
from apps.crm.models import Lead, Task
from apps.industries.models import Industry
from apps.tenancy.context import company_context
from apps.voice import handoff
from apps.voice.models import Handoff
from apps.webchat import services as chat
from apps.webchat.models import ChatWidget

from .test_ai_engine import FakeLLM
from .test_voice_handoff import agent

SITE = "https://www.alpha-homes.example"


@pytest.fixture
def realty(company_a, set_setting):
    set_setting("chat.bot_min_seconds", 0)
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
def widget(sara, realty):
    with company_context(realty.id):
        w = chat.widget_for(sara)
        return chat.save_widget(w, {"allowed_domains": "alpha-homes.example"})


@pytest.fixture
def visitor():
    return Client(HTTP_ORIGIN=SITE)


def url(widget, path=""):
    return f"/public/v1/chat/{widget.key}/{path}"


def open_chat(client, widget, **body):
    r = client.post(url(widget, "sessions/"), {"language": "en", **body}, content_type="application/json")
    assert r.status_code == 201, r.content
    return r.json()


def say(client, widget, token, text):
    return client.post(
        url(widget, "messages/"), {"text": text}, content_type="application/json", HTTP_X_CHAT_TOKEN=token
    )


# ---------------------------------------------------------------- CHAT-01 / 02 settings, snippet, appearance
@pytest.mark.django_db
def test_widget_settings_validate_and_give_the_snippet(widget, realty):
    with company_context(realty.id):
        assert widget.key.startswith("wk_") and widget.allowed_domains == ["alpha-homes.example"]
        assert f'data-key="{widget.key}"' in chat.snippet(widget) and "webchat/widget.js" in chat.snippet(widget)
        w = chat.save_widget(widget, {"allowed_domains": ["https://Shop.Example.com/contact", "localhost:5500"]})
        assert w.allowed_domains == ["localhost:5500", "shop.example.com"]
        for bad in ({"color": "red"}, {"allowed_domains": "not a site"}, {"language": "xx"}, {"position": "top"}):
            with pytest.raises(ValidationError):
                chat.save_widget(widget, bad)
            widget.refresh_from_db()
        old = widget.key
        assert chat.save_widget(widget, {"regenerate_key": True}).key != old


@pytest.mark.django_db
def test_public_config_comes_from_settings_languages_and_the_employee(widget, visitor, set_setting, realty):
    set_setting("general.widget_powered_by", "Powered by Test Platform")
    r = visitor.get(url(widget))
    assert r.status_code == 200 and r["Access-Control-Allow-Origin"] == SITE
    cfg = r.json()
    assert cfg["title"] == "Sara" and cfg["subtitle"] == realty.name and cfg["powered_by"] == "Powered by Test Platform"
    assert cfg["texts"]["en"]["launcher"] == "Chat with our AI Employee" and cfg["texts"]["en"]["send"] == "Send"
    assert set(cfg["actions"]) == {k for k, _ in ChatWidget.ACTIONS}
    with company_context(realty.id):
        chat.save_widget(widget, {"title": "Sara (Alpha)", "launcher_text": {"en": "Ask Sara"}, "color": "#112233"})
    cfg = visitor.get(url(widget)).json()
    assert cfg["title"] == "Sara (Alpha)" and cfg["texts"]["en"]["launcher"] == "Ask Sara" and cfg["color"] == "#112233"


# ---------------------------------------------------------------- CHAT-05 security
@pytest.mark.django_db
def test_only_allowed_websites_active_employees_and_known_keys(widget, sara, set_setting, realty):
    assert Client(HTTP_ORIGIN="https://shop.alpha-homes.example").get(url(widget)).status_code == 200  # sub-domain
    assert Client(HTTP_ORIGIN="https://evil.example").get(url(widget)).status_code == 403
    assert Client(HTTP_ORIGIN=SITE).get("/public/v1/chat/wk_unknown/").status_code == 404
    with company_context(realty.id):
        chat.save_widget(widget, {"allowed_domains": []})
    assert Client(HTTP_ORIGIN="https://any.example").get(url(widget)).status_code == 403  # list required
    set_setting("chat.require_allowed_domains", False)
    assert Client(HTTP_ORIGIN="https://any.example").get(url(widget)).status_code == 200
    AIEmployee.all_companies.filter(pk=sara.pk).update(status=AIEmployee.PAUSED)
    assert Client(HTTP_ORIGIN=SITE).get(url(widget)).status_code == 404
    AIEmployee.all_companies.filter(pk=sara.pk).update(status=AIEmployee.ACTIVE)
    ChatWidget.all_companies.filter(pk=widget.pk).update(is_enabled=False)
    assert Client(HTTP_ORIGIN=SITE).get(url(widget)).status_code == 404


@pytest.mark.django_db
def test_rate_limit_honeypot_and_bot_timing(widget, visitor, set_setting, monkeypatch):
    FakeLLM(monkeypatch, [{"text": "Hello!"}] * 5)
    assert (
        visitor.post(url(widget, "sessions/"), {"website": "spam"}, content_type="application/json").status_code == 400
    )
    set_setting("chat.bot_min_seconds", 5)
    token = open_chat(visitor, widget)["token"]
    assert say(visitor, widget, token, "hi").status_code == 400  # typed faster than a person
    set_setting("chat.bot_min_seconds", 0)
    set_setting("chat.rate_messages", "3/minute")  # the refused message above counts too
    assert say(visitor, widget, token, "one").status_code == 200
    assert say(visitor, widget, token, "two").status_code == 200
    assert say(visitor, widget, token, "three").status_code == 429
    assert say(visitor, widget, "forged-token", "x").status_code in (404, 429)


# ---------------------------------------------------------------- the visitor's conversation
@pytest.mark.django_db
def test_visitor_chats_with_the_ai_and_the_chat_is_saved_like_every_conversation(widget, visitor, realty, monkeypatch):
    with company_context(realty.id):
        chat.save_widget(widget, {"greetings": {"en": "Welcome to {{ company_name }}! Looking for a home?"}})
    fake = FakeLLM(
        monkeypatch,
        [{"calls": [("create_lead", {"name": "Ravi Kumar", "phone": "9876543210"})]}, {"text": "Thanks Ravi!"}],
        analysis={"summary": {"summary": "Wants a 2 BHK.", "outcome": "Interested", "confidence": 0.9}},
    )
    data = open_chat(visitor, widget, page=SITE + "/flats")
    opening = data["messages"][0]
    assert opening["role"] == "ai" and "AI" in opening["text"] and f"Welcome to {realty.name}!" in opening["text"]
    r = say(visitor, widget, data["token"], "I am Ravi, 9876543210, need a 2 BHK")
    body = r.json()
    assert r.status_code == 200 and [m["role"] for m in body["messages"]] == ["ai", "customer", "ai"]
    assert body["messages"][-1]["text"] == "Thanks Ravi!" and body["handled_by"] == "ai"
    assert fake.calls[0]["task"] == "chat_dialog"
    # polling returns only what is new
    last = body["messages"][-1]["id"]
    assert visitor.get(url(widget, f"messages/?after={last}"), HTTP_X_CHAT_TOKEN=data["token"]).json()["messages"] == []
    assert visitor.post(url(widget, "end/"), HTTP_X_CHAT_TOKEN=data["token"]).status_code == 200
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="web_chat")
        assert conv.status == "ended" and conv.summary == "Wants a 2 BHK." and conv.customer["page"].endswith("/flats")
        lead = Lead.objects.get(phone="+919876543210")
        assert conv.lead == lead and lead.source.key == "website_chat"  # CHAT-04
    # an ended chat cannot be written into
    assert say(visitor, widget, data["token"], "hello?").status_code == 400


@pytest.mark.django_db
def test_enquiry_and_callback_forms_create_the_lead_note_and_task(widget, visitor, realty):
    data = open_chat(visitor, widget)
    form = {"kind": "callback", "name": "Meera", "phone": "9123456780", "message": "Call me after 6 pm"}
    r = visitor.post(url(widget, "contact/"), form, content_type="application/json", HTTP_X_CHAT_TOKEN=data["token"])
    assert r.status_code == 200 and r.json()["messages"][-1]["notice"] == "chat_thanks"
    with company_context(realty.id):
        lead = Lead.objects.get(phone="+919123456780")
        assert lead.name == "Meera" and lead.source.key == "website_chat" and lead.created_via == "website"
        assert Task.objects.filter(lead=lead, type="callback").exists()
        assert Conversation.objects.get(channel="web_chat").lead == lead
    bad = {**form, "phone": ""}
    assert visitor.post(url(widget, "contact/"), bad, content_type="application/json").status_code == 400
    with company_context(realty.id):
        chat.save_widget(widget, {"actions": {"enquiry": True, "callback": False, "book": True, "human": True}})
    assert visitor.post(url(widget, "contact/"), form, content_type="application/json").status_code == 400


# ---------------------------------------------------------------- handoff to a person (HO-01 chat, CHAT-06)
@pytest.mark.django_db
def test_visitor_asks_for_a_person_agent_takes_over_replies_and_hands_back(widget, visitor, realty, monkeypatch):
    asha = agent(realty, "asha@alpha.example")
    fake = FakeLLM(monkeypatch, [{"text": "Back to you."}])
    data = open_chat(visitor, widget)
    token = data["token"]
    r = visitor.post(url(widget, "human/"), HTTP_X_CHAT_TOKEN=token)
    assert r.json()["handled_by"] == "waiting" and r.json()["messages"][-1]["notice"] == "chat_waiting"
    with company_context(realty.id):
        h = Handoff.objects.get()
        assert h.status == Handoff.RINGING and h.assigned_user == asha and h.channel == "web_chat"
    assert mail.outbox and mail.outbox[-1].to == ["asha@alpha.example"]
    # the agent accepts the screen pop → takes the chat over
    team = Client()
    team.force_login(asha)
    assert team.post(f"/api/v1/handoffs/{h.pk}/accept/").status_code == 200
    state = visitor.get(url(widget, "messages/"), HTTP_X_CHAT_TOKEN=token).json()
    assert state["handled_by"] == "human" and state["agent"] == "Asha"
    assert state["messages"][-1]["notice"] == "chat_joined" and state["messages"][-1]["name"] == "Asha"
    # visitor writes: the AI stays quiet
    calls = len(fake.calls)
    assert say(visitor, widget, token, "Is parking included?").json()["messages"][-1]["role"] == "customer"
    assert len(fake.calls) == calls
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="web_chat")
    r = team.post(
        f"/api/v1/inbox/{conv.pk}/reply/", {"text": "Yes, one covered slot."}, content_type="application/json"
    )
    assert r.status_code == 200 and r.json()["messages"][-1]["role"] == "human"
    seen = visitor.get(url(widget, "messages/"), HTTP_X_CHAT_TOKEN=token).json()["messages"]
    assert any(m["role"] == "human" and m["name"] == "Asha" and "covered" in m["text"] for m in seen)
    # hand back: the AI answers again
    assert team.post(f"/api/v1/inbox/{conv.pk}/hand-back/").json()["handled_by"] == "ai"
    assert say(visitor, widget, token, "Thanks").json()["messages"][-1]["text"] == "Back to you."
    with company_context(realty.id):
        assert Handoff.objects.get().status == Handoff.COMPLETED


@pytest.mark.django_db
def test_no_agent_tells_the_visitor_and_asks_for_contact_details(widget, visitor, realty):
    data = open_chat(visitor, widget)
    body = visitor.post(url(widget, "human/"), HTTP_X_CHAT_TOKEN=data["token"]).json()
    assert body["handled_by"] == "ai"
    last = body["messages"][-1]
    assert last["role"] == "ai" and last.get("ask_contact") is True and "busy" in last["text"]
    with company_context(realty.id):
        assert Handoff.objects.get().status == Handoff.NO_AGENT


@pytest.mark.django_db
def test_unanswered_chat_handoff_moves_to_the_next_agent(widget, visitor, realty, set_setting):
    set_setting("handoff.agent_ring_seconds", 5)
    first = agent(realty, "a1@alpha.example")
    second = agent(realty, "a2@alpha.example")
    data = open_chat(visitor, widget)
    visitor.post(url(widget, "human/"), HTTP_X_CHAT_TOKEN=data["token"])
    with company_context(realty.id):
        h = Handoff.objects.get()
        tried = h.assigned_user
        Handoff.objects.filter(pk=h.pk).update(updated_at=timezone.now() - dt.timedelta(seconds=30))
    handoff.expire_ringing()  # the minute cron (the widget poll does the same for its own chat)
    with company_context(realty.id):
        h.refresh_from_db()
        assert h.status == Handoff.RINGING and h.assigned_user != tried and {first, second} >= {tried, h.assigned_user}


@pytest.mark.django_db
def test_ai_hands_over_on_chats_with_the_transfer_tool_and_keyword_trigger(widget, visitor, sara, realty, monkeypatch):
    agent(realty, "asha@alpha.example")
    with company_context(realty.id):
        conv = chat.start(widget, "en")
        names = [d["name"] for d in toolkit.definitions(toolkit.ToolContext(realty, sara, conv), toolkit.enabled(sara))]
        assert "transfer_call" in names
    FakeLLM(monkeypatch, [{"calls": [("transfer_call", {"reason": "wants the manager"})]}, {"text": "Connecting you."}])
    token = open_chat(visitor, widget)["token"]
    assert say(visitor, widget, token, "let me talk to your manager").json()["handled_by"] == "waiting"
    # keyword rule (HO-01 configurable trigger) on a fresh chat
    AIEmployee.all_companies.filter(pk=sara.pk).update(rules={**sara.rules, "handoff_keywords": ["complaint"]})
    FakeLLM(monkeypatch, [{"text": "Sorry to hear that."}])
    token = open_chat(visitor, widget)["token"]
    say(visitor, widget, token, "I have a complaint")
    with company_context(realty.id):  # Asha still has the first chat ringing, so this one finds no agent
        assert Handoff.objects.filter(reason="keyword", status=Handoff.NO_AGENT).exists()


# ---------------------------------------------------------------- inbox API: views, permissions, isolation
@pytest.mark.django_db
def test_inbox_lists_live_chats_and_checks_permissions(widget, visitor, realty, owner_a, owner_b, monkeypatch):
    FakeLLM(monkeypatch, [{"text": "Hi!"}])
    token = open_chat(visitor, widget)["token"]
    say(visitor, widget, token, "hello")
    owner = Client()
    owner.force_login(owner_a)
    rows = owner.get("/api/v1/inbox/").json()["results"]
    assert len(rows) == 1 and rows[0]["preview"]["text"] == "Hi!" and rows[0]["handled_by"] == "ai"
    assert owner.get("/api/v1/inbox/?view=waiting").json()["results"] == []
    conv_id = rows[0]["id"]
    detail = owner.get(f"/api/v1/inbox/{conv_id}/").json()
    assert detail["can_answer"] is True and len(detail["messages"]) == 3
    # take over and assign
    assert owner.post(f"/api/v1/inbox/{conv_id}/take-over/").json()["handled_by"] == "human"
    assert owner.get("/api/v1/inbox/?view=mine").json()["results"][0]["id"] == conv_id
    viewer = agent(realty, "viewer@alpha.example", role="agent")
    r = owner.post(f"/api/v1/inbox/{conv_id}/assign/", {"user": str(viewer.pk)}, content_type="application/json")
    assert r.status_code == 200 and r.json()["assigned_name"]
    # another company sees nothing
    other = Client()
    other.force_login(owner_b)
    assert other.get("/api/v1/inbox/").json()["results"] == []
    assert other.get(f"/api/v1/inbox/{conv_id}/").status_code == 404
    # ending saves the record
    assert owner.post(f"/api/v1/inbox/{conv_id}/end/").json()["status"] == "ended"
    assert owner.get("/api/v1/inbox/?view=ended").json()["results"][0]["id"] == conv_id


@pytest.mark.django_db
def test_people_without_handoff_permission_cannot_answer(widget, visitor, realty):
    token = open_chat(visitor, widget)["token"]
    with company_context(realty.id):
        conv = chat.conversation_for(widget, token)
    from apps.accounts.models import User
    from apps.rbac.models import Role
    from apps.tenancy.services import add_member

    from .conftest import make_user

    role = Role.objects.create(scope="company", key="viewer", name="Viewer", permissions=["conversations.view"])
    make_user("look@alpha.example")
    add_member(realty, "look@alpha.example", role)
    c = Client()
    c.force_login(User.objects.get(email="look@alpha.example"))
    assert c.get("/api/v1/inbox/").status_code == 200
    assert c.post(f"/api/v1/inbox/{conv.pk}/reply/", {"text": "hi"}, content_type="application/json").status_code == 403
    with company_context(realty.id), pytest.raises(ValidationError):
        inbox.reply(conv, User.objects.get(email="look@alpha.example"), "hi")


# ---------------------------------------------------------------- panel pages
@pytest.mark.django_db
def test_panel_widget_page_preview_and_inbox(widget, visitor, sara, realty, owner_a, monkeypatch):
    c = Client()
    c.force_login(owner_a)
    page = c.get(f"/app/ai-employees/{sara.pk}/website-chat/")
    assert page.status_code == 200 and widget.key.encode() in page.content and b"Copy code" in page.content
    r = c.post(
        f"/app/ai-employees/{sara.pk}/website-chat/",
        {
            "is_enabled": "on",
            "title": "Sara",
            "position": "left",
            "allowed_domains": "alpha-homes.example\nwww.alpha.example",
            "action_human": "on",
            "action_enquiry": "on",
        },
    )
    assert r.status_code == 302
    widget.refresh_from_db()
    assert widget.position == "left" and widget.allowed_domains == ["alpha-homes.example", "www.alpha.example"]
    assert widget.actions == {"enquiry": True, "callback": False, "book": False, "human": True}
    preview = c.get(f"/app/ai-employees/{sara.pk}/website-chat/preview/")
    assert preview.status_code == 200 and f'data-key="{widget.key}"'.encode() in preview.content
    FakeLLM(monkeypatch, [{"text": "Hi!"}])
    say(visitor, widget, open_chat(visitor, widget)["token"], "hello")
    assert c.get("/app/inbox/").status_code == 200
    with company_context(realty.id):
        conv = Conversation.objects.get(channel="web_chat")
    detail = c.get(f"/app/inbox/{conv.pk}/")
    assert detail.status_code == 200 and b"Take over" in detail.content
    assert c.get(f"/app/conversations/{conv.pk}/").status_code == 200
    with company_context(realty.id):
        checks = {c["key"]: c["ok"] for c in employees.readiness(sara)}
    assert checks["channel"] is True  # the website chat counts as a connected channel
