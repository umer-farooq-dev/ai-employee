"""Phase 4 REST API (mobile app + panels): AI Employees, test console, knowledge, tools registry, Super Admin views."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.agents.models import AIEmployee
from apps.industries.models import Industry
from apps.rbac.models import Role
from apps.roles_tools.models import Tool
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
def api(owner_a, realty):
    c = Client()
    c.force_login(owner_a)
    return c


def j(client, method, url, data=None):
    return getattr(client, method)(url, data or {}, content_type="application/json")


@pytest.mark.django_db
def test_employee_wizard_test_console_and_activation_over_api(api, realty, monkeypatch):
    opts = api.get("/api/v1/ai-employees/options/").json()
    assert {r["key"] for r in opts["roles"]} >= {"sales_executive", "follow_up"}
    assert [s["key"] for s in opts["wizard_steps"]][0] == "industry" and len(opts["wizard_steps"]) == 10

    r = j(api, "post", "/api/v1/ai-employees/", {"role": "sales_executive", "name": "Sara"})
    assert r.status_code == 201, r.content
    emp = r.json()
    assert emp["industry_key"] == "real-estate" and emp["status"] == "draft" and emp["config_version"] == 1
    url = f"/api/v1/ai-employees/{emp['id']}/"
    r = j(
        api,
        "patch",
        url,
        {
            "persona": {"tone": "formal"},
            "languages": ["en", "hi"],
            "primary_language": "en",
            "rules": {"restricted_topics": "Politics\nReligion"},
            "tools": {"send_email": False},
        },
    )
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["config_version"] == 2 and body["rules"]["restricted_topics"] == ["Politics", "Religion"]
    tools = {t["key"]: t["enabled"] for t in api.get(url + "tools/").json()}
    assert tools["send_email"] is False and tools["match_properties"] is True
    assert [v["version"] for v in api.get(url + "versions/").json()] == [2, 1]

    FakeLLM(monkeypatch, [{"text": "Namaste! Kaise madad karun?"}])
    conv = api.post(url + "test-sessions/", {}, content_type="application/json").json()
    assert conv["messages"][0]["meta"]["disclosure"] is True
    reply = j(api, "post", f"/api/v1/conversations/{conv['id']}/messages/", {"text": "hello"}).json()
    assert reply["message"]["content"] == "Namaste! Kaise madad karun?"
    assert j(api, "post", url + "test-passed/").json()["test_passed"] is True

    blocked = j(api, "post", url + "activate/")
    assert blocked.status_code == 400 and "knowledge" in str(blocked.json()).lower()
    src = j(api, "post", "/api/v1/kb/sources/", {"type": "text", "title": "About", "body": "We build homes in Pune."})
    assert src.status_code == 201 and src.json()["status"] == "ready"
    assert j(api, "post", f"/api/v1/kb/sources/{src.json()['id']}/approve/").json()["approval"] == "approved"
    assert j(api, "post", url + "activate/").json()["status"] == "active"
    readiness = {c["key"]: c for c in api.get(url + "readiness/").json()}
    assert readiness["channel"]["required"] is False

    convs = api.get("/api/v1/conversations/?test=1").json()["results"]
    assert convs[0]["id"] == conv["id"]
    detail = api.get(f"/api/v1/conversations/{conv['id']}/").json()
    assert [m["role"] for m in detail["messages"]] == ["ai", "customer", "ai"]
    assert j(api, "post", f"/api/v1/conversations/{conv['id']}/end/").json()["status"] == "ended"
    assert api.delete(url).status_code == 204 and AIEmployee.all_companies.get(pk=emp["id"]).status == "archived"


@pytest.mark.django_db
def test_knowledge_api_files_faqs_test_and_unanswered(api, realty, monkeypatch):
    upload = SimpleUploadedFile("prices.csv", b"Project,Price\nGreen Valley,85 lakh\n", content_type="text/csv")
    r = api.post("/api/v1/kb/sources/", {"type": "sheet", "title": "Prices", "file": upload})
    assert r.status_code == 201 and r.json()["chunks"] == 1 and r.json()["file_url"].startswith("/")
    faqs = j(api, "post", "/api/v1/kb/sources/", {"type": "faq", "title": "General"}).json()
    faq = j(api, "post", "/api/v1/kb/faqs/", {"source": faqs["id"], "question": "Parking?", "answer": "Yes, covered."})
    assert faq.status_code == 201 and faq.json()["approval"] == "draft"
    assert j(api, "post", f"/api/v1/kb/faqs/{faq.json()['id']}/approve/").json()["approval"] == "approved"
    csv = SimpleUploadedFile("faqs.csv", b"question,answer\nLift?,Yes\n", content_type="text/csv")
    assert api.post("/api/v1/kb/faqs/import/", {"source": faqs["id"], "file": csv}).json() == {"imported": 1}

    FakeLLM(monkeypatch, [{"text": "Yes, covered parking [K1]."}])
    result = j(api, "post", "/api/v1/kb/test-query/", {"question": "Is there parking?"}).json()
    assert result["found"] and result["sources"][0]["faq"] == faq.json()["id"]
    from apps.knowledge.services import log_unanswered
    from apps.tenancy.context import company_context

    with company_context(realty.id):
        log_unanswered(realty, "Is there a gym?")
    items = api.get("/api/v1/kb/unanswered/").json()["results"]
    assert items[0]["example_text"] == "Is there a gym?"
    assert j(api, "post", f"/api/v1/kb/unanswered/{items[0]['id']}/resolve/").json()["status"] == "resolved"


@pytest.mark.django_db
def test_company_isolation_and_permissions(api, realty, owner_b, company_b):
    emp = j(api, "post", "/api/v1/ai-employees/", {"role": "receptionist"}).json()
    src = j(api, "post", "/api/v1/kb/sources/", {"type": "text", "title": "Secret", "body": "Alpha only."}).json()
    other = Client()
    other.force_login(owner_b)
    assert other.get(f"/api/v1/ai-employees/{emp['id']}/").status_code == 404
    assert other.get(f"/api/v1/kb/sources/{src['id']}/").status_code == 404
    assert other.get("/api/v1/ai-employees/").json()["results"] == []
    assert j(other, "post", f"/api/v1/ai-employees/{emp['id']}/test-sessions/").status_code == 404

    agent = make_user("agent@alpha.example")
    add_member(realty, agent.email, Role.objects.get(scope="company", key="agent"))
    c = Client()
    c.force_login(agent)
    assert c.get("/api/v1/ai-employees/").status_code == 200  # view only
    assert j(c, "post", "/api/v1/ai-employees/", {"role": "receptionist"}).status_code == 403
    assert j(c, "post", f"/api/v1/kb/sources/{src['id']}/approve/").status_code == 403
    assert j(c, "post", f"/api/v1/ai-employees/{emp['id']}/test-sessions/").status_code == 403


@pytest.mark.django_db
def test_admin_tools_registry_and_ai_oversight(admin_client, realty, owner_a, monkeypatch):
    tools = admin_client.get("/api/v1/admin/tools/").json()
    keys = {t["key"] for t in tools}
    assert {"create_lead", "search_property", "book_counselling", "send_email"} <= keys
    r = j(
        admin_client,
        "post",
        "/api/v1/admin/tools/",
        {
            "key": "search_cars",
            "name": "Search cars",
            "description": "Search cars",
            "category": "industry",
            "handler": "catalog_search",
            "config": {"catalog_type": "car"},
            "industries": ["real-estate"],
        },
    )
    assert r.status_code == 201, r.content
    assert (
        j(
            admin_client,
            "post",
            "/api/v1/admin/tools/",
            {"key": "x", "name": "x", "description": "x", "handler": "rm_rf"},
        ).status_code
        == 400
    )
    j(admin_client, "patch", f"/api/v1/admin/tools/{r.json()['id']}/", {"is_active": False})
    assert Tool.objects.get(key="search_cars").is_active is False

    made = j(admin_client, "post", f"/api/v1/admin/companies/{realty.pk}/ai-employee/")
    assert made.status_code == 201 and made.json()["company_name"] == realty.name
    listing = admin_client.get("/api/v1/admin/ai-employees/").json()["results"]
    emp_id = listing[0]["id"]
    paused = j(admin_client, "post", f"/api/v1/admin/ai-employees/{emp_id}/pause/", {"reason": "Spam calls"}).json()
    assert paused["status"] == "paused" and paused["paused_by_platform"] is True
    changed = j(admin_client, "post", f"/api/v1/admin/ai-employees/{emp_id}/change-role/", {"role": "receptionist"})
    assert changed.json()["role_key"] == "receptionist"
    assert (
        j(admin_client, "post", f"/api/v1/admin/ai-employees/{emp_id}/release/").json()["paused_by_platform"] is False
    )

    owner = Client()
    owner.force_login(owner_a)
    FakeLLM(monkeypatch, [{"text": "Hi"}])
    conv = j(owner, "post", f"/api/v1/ai-employees/{emp_id}/test-sessions/").json()
    detail = admin_client.get(f"/api/v1/admin/conversations/{conv['id']}/").json()
    assert detail["employee_name"] and detail["messages"]
    assert owner.get("/api/v1/admin/ai-employees/").status_code == 403


@pytest.mark.django_db
def test_openapi_lists_phase4_endpoints(admin_client):
    paths = set(admin_client.get("/api/v1/schema/", HTTP_ACCEPT="application/json").json()["paths"])
    for p in (
        "/api/v1/ai-employees/",
        "/api/v1/ai-employees/{id}/test-sessions/",
        "/api/v1/conversations/{id}/messages/",
        "/api/v1/kb/sources/",
        "/api/v1/kb/test-query/",
        "/api/v1/kb/unanswered/",
        "/api/v1/admin/tools/",
        "/api/v1/admin/ai-employees/",
        "/api/v1/admin/ai-providers/",
    ):
        assert p in paths, p
