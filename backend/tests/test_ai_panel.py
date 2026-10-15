"""Phase 4 screens: company panel (AI Employees wizard, test console, knowledge, conversations, catalogue matching)
and Super Admin (tool registry, AI Employees of all companies, conversation viewer)."""

import pytest
from django.test import Client

from apps.agents.models import AIEmployee, Conversation
from apps.industries.models import Industry
from apps.knowledge.models import FAQ, Source
from apps.rbac.models import Role
from apps.roles_tools.models import EmployeeRole, Tool
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member

from .conftest import make_user
from .test_ai_engine import FakeLLM


@pytest.fixture
def realty(company_a):
    industry = Industry.objects.get(key="real-estate")
    company_a.industry, company_a.template_version = industry, industry.published_version
    company_a.save()
    return company_a


@pytest.fixture
def owner(owner_a, realty):
    c = Client()
    c.force_login(owner_a)
    return c


def ok(response):
    assert response.status_code == 200, response.content[:500]
    return response.content.decode()


@pytest.mark.django_db
def test_wizard_end_to_end_in_the_panel(owner, realty, monkeypatch):
    assert "Create your first AI Employee" in ok(owner.get("/app/ai-employees/"))
    html = ok(owner.get("/app/ai-employees/new/"))
    assert "Sales Executive" in html and "Follow-up Employee" in html
    r = owner.post("/app/ai-employees/new/", {"industry": "real-estate", "role": "sales_executive", "name": "Sara"})
    emp = AIEmployee.all_companies.get(company=realty)
    assert r.status_code == 302 and r.url.endswith(f"/app/ai-employees/{emp.pk}/setup/identity/")
    base = f"/app/ai-employees/{emp.pk}/setup/"
    for step in ("identity", "voice", "languages", "knowledge", "tools", "rules", "test", "activate"):
        ok(owner.get(base + step + "/"))
    r = owner.post(
        base + "identity/",
        {
            "name": "Sara",
            "tone": "formal",
            "description": "Senior consultant",
            "greeting_en": "Hi from {{ company_name }}!",
            "greeting_hi": "",
            "greeting_bn": "",
        },
    )
    assert r.status_code == 302 and r.url.endswith("/voice/")
    owner.post(base + "voice/", {"speed": "1.2"})
    owner.post(base + "languages/", {"primary_language": "hi", "languages": ["en"]})
    owner.post(base + "tools/", {"tools": ["create_lead", "update_lead", "match_properties"]})
    r = owner.post(
        base + "rules/",
        {
            "after_hours_message": "Closed now",
            "max_call_minutes": "10",
            "escalation_triggers": "Asks for a human\nAngry",
            "restricted_topics": "Politics",
            "fallback_action": "callback",
            "fallback_en": "Our team will call you.",
            "follow_up_enabled": "on",
            "follow_up_hours": "12",
            "q_field": ["budget", "bhk"],
            "q_text": ["Aapka budget kitna hai?", "Kitne BHK?"],
            "recording": "on",
        },
    )
    assert r.status_code == 302, r.content[:400]
    emp.refresh_from_db()
    assert emp.persona["tone"] == "formal" and emp.voices["speed"] == 1.2
    assert emp.primary_language == "hi" and emp.languages == ["hi", "en"]
    assert emp.tools["send_email"] is False and emp.tools["match_properties"] is True
    assert (
        emp.rules["escalation_triggers"] == ["Asks for a human", "Angry"]
        and emp.rules["follow_up"]["after_hours"] == 12
    )
    assert [q["field"] for q in emp.qualification] == ["budget", "bhk"]
    assert emp.config_version > 1 and emp.wizard_step >= 8

    html = ok(owner.get(base + "test/"))
    assert "/api/v1/ai-employees/" in html and "Test passed" in html
    FakeLLM(monkeypatch, [{"text": "Namaste"}])
    conv = owner.post(f"/api/v1/ai-employees/{emp.pk}/test-sessions/", {}, content_type="application/json").json()
    owner.post(f"/api/v1/conversations/{conv['id']}/messages/", {"text": "hi"}, content_type="application/json")
    assert owner.post(base + "test/").status_code == 302
    html = ok(owner.get(base + "activate/"))
    assert "Approved knowledge" in html and "Required" in html

    detail = ok(owner.get(f"/app/ai-employees/{emp.pk}/"))
    assert "Settings history" in detail and "Recent conversations" in detail
    convs = ok(owner.get("/app/conversations/?test=1"))
    assert "Sara" in convs
    transcript = ok(owner.get(f"/app/conversations/{conv['id']}/"))
    assert "Namaste" in transcript and "AI disclosure" in transcript


@pytest.mark.django_db
def test_knowledge_screens(owner, realty, monkeypatch):
    assert "Add Website" in ok(owner.get("/app/knowledge/"))
    for kind in ("url", "pdf", "docx", "text", "sheet", "faq"):
        ok(owner.get(f"/app/knowledge/new/?type={kind}"))
    r = owner.post(
        "/app/knowledge/new/", {"type": "text", "title": "Timings", "body": "Open 10 am to 6 pm.", "scope": "all"}
    )
    source = Source.all_companies.get(company=realty, title="Timings")
    assert r.status_code == 302 and source.status == "ready"
    ok(owner.get(f"/app/knowledge/{source.pk}/"))
    owner.post("/app/knowledge/", {"source": source.pk, "op": "approve"})
    source.refresh_from_db()
    assert source.approval == "approved"

    owner.post("/app/knowledge/new/", {"type": "faq", "title": "General", "scope": "all"})
    faqs = Source.all_companies.get(company=realty, type="faq", title="General")
    owner.post(f"/app/knowledge/{faqs.pk}/", {"op": "faq_add", "question": "Parking?", "answer": "Yes"})
    faq = FAQ.all_companies.get(source=faqs)
    owner.post(f"/app/knowledge/{faqs.pk}/", {"op": "faq_approve", "faq": faq.pk})
    faq.refresh_from_db()
    assert faq.approval == "approved" and "Parking?" in ok(owner.get(f"/app/knowledge/{faqs.pk}/"))

    FakeLLM(monkeypatch, [{"text": "Open 10 am to 6 pm [K1]."}])
    html = ok(owner.post("/app/knowledge/test/", {"question": "When are you open?"}))
    assert "Open 10 am to 6 pm." in html and "Timings" in html
    from apps.knowledge.services import log_unanswered

    with company_context(realty.id):
        log_unanswered(realty, "Do you have a gym?")
    assert "Do you have a gym?" in ok(owner.get("/app/knowledge/unanswered/"))


@pytest.mark.django_db
def test_catalogue_matching_settings(owner, realty):
    ok(owner.get("/app/catalogue/property/matching/"))
    owner.post(
        "/app/catalogue/property/matching/",
        {"budget_tolerance_percent": "15", "location_aliases": "New Town: Rajarhat, Action Area"},
    )
    realty.refresh_from_db()
    assert realty.settings["catalog_match"]["property"] == {
        "budget_tolerance_percent": 15.0,
        "location_aliases": {"new town": ["rajarhat", "action area"]},
    }


@pytest.mark.django_db
def test_agent_can_view_but_not_change(realty, owner):
    owner.post("/app/ai-employees/new/", {"industry": "real-estate", "role": "receptionist", "name": "Riya"})
    emp = AIEmployee.all_companies.get(company=realty)
    agent = make_user("agent@alpha.example")
    add_member(realty, agent.email, Role.objects.get(scope="company", key="agent"))
    c = Client()
    c.force_login(agent)
    html = ok(c.get("/app/ai-employees/"))
    assert "Riya" in html and "New AI Employee" not in html
    assert c.get("/app/ai-employees/new/").status_code == 403
    assert c.post(f"/app/ai-employees/{emp.pk}/setup/identity/", {"name": "X"}).status_code == 403
    assert c.post("/app/knowledge/new/", {"type": "text", "title": "x", "body": "y"}).status_code == 403


@pytest.mark.django_db
def test_menu_links_to_phase4_screens(owner):
    html = ok(owner.get("/app/"))
    for url in ("/app/ai-employees/", "/app/knowledge/", "/app/conversations/"):
        assert f'href="{url}"' in html, url


@pytest.mark.django_db
def test_super_admin_screens(admin_client, realty, owner, monkeypatch):
    html = ok(admin_client.get("/superadmin/tools/"))
    assert "search_property" in html and "catalog_match" in html
    tool = Tool.objects.get(key="search_property")
    ok(admin_client.get(f"/superadmin/platform/tools/{tool.pk}/"))
    r = admin_client.post(
        "/superadmin/platform/tools/new/",
        {
            "key": "search_cars",
            "name": "Search cars",
            "description": "Search cars",
            "category": "industry",
            "handler": "catalog_search",
            "side_effect": "read",
            "timeout_ms": "5000",
            "sort_order": "1",
            "config_json": '{"catalog_type": "car"}',
            "schema_json": "{}",
            "is_active": "on",
        },
    )
    assert r.status_code == 302 and Tool.objects.get(key="search_cars").config == {"catalog_type": "car"}
    follow_up = EmployeeRole.objects.get(key="follow_up")
    role_form = ok(admin_client.get(f"/superadmin/platform/employee-roles/{follow_up.pk}/"))
    assert "match_properties" in role_form

    assert "AI Employees" in ok(admin_client.get(f"/superadmin/companies/{realty.pk}/"))
    r = admin_client.post("/superadmin/ai-employees/", {"company": realty.pk})
    emp = AIEmployee.all_companies.get(company=realty)
    assert r.status_code == 302 and emp.status == "draft"
    assert emp.name in ok(admin_client.get("/superadmin/ai-employees/"))
    admin_client.post(f"/superadmin/ai-employees/{emp.pk}/", {"op": "pause", "reason": "Spam"})
    emp.refresh_from_db()
    assert emp.paused_by_platform and emp.status == "paused"
    assert "platform pause" in ok(admin_client.get(f"/superadmin/ai-employees/{emp.pk}/"))
    FakeLLM(monkeypatch, [{"text": "Hello"}])
    conv = owner.post(f"/api/v1/ai-employees/{emp.pk}/test-sessions/", {}, content_type="application/json").json()
    assert Conversation.all_companies.filter(pk=conv["id"]).exists()
    assert "AI disclosure" in ok(admin_client.get(f"/superadmin/conversations/{conv['id']}/"))
    settings_html = ok(admin_client.get("/superadmin/settings/system/?tab=ai"))
    assert (
        "Platform guardrails" in settings_html and "Fallback message (when facts are missing) — Hindi" in settings_html
    )
    assert "Website: maximum pages" in ok(admin_client.get("/superadmin/settings/system/?tab=knowledge"))
