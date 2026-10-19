"""Phase 3 part 2: CRM (CRM-01 … CRM-18, SCORE-02, CP-04) — panel, services and API, with company isolation."""

import io
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.billing.models import Plan, PlanEntitlement
from apps.crm import imports
from apps.crm import services as crm
from apps.crm.models import AssignmentRule, Lead, LeadActivity, LeadImport, Task
from apps.industries.models import FieldDefinition, Industry, ScoringRule
from apps.rbac.models import Role
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member

from .conftest import make_user


@pytest.fixture
def realty(company_a):
    industry = Industry.objects.get(key="real-estate")
    company_a.industry, company_a.template_version = industry, industry.published_version
    company_a.save()
    return company_a


@pytest.fixture
def owner(client, owner_a, realty):
    client.force_login(owner_a)
    return client


@pytest.fixture
def agent_a(realty):
    user = make_user("agent@alpha.example")
    add_member(realty, user.email, Role.objects.get(scope="company", key="agent"))
    return user


def new_lead(company, **data):
    with company_context(company.id):
        return crm.create_lead(company, {"name": "Test", **data})


# ---------------------------------------------------------------- create, numbers, duplicates, scoring
@pytest.mark.django_db
def test_create_lead_with_industry_fields_and_score(owner, realty, settings):
    response = owner.post(
        "/app/leads/new/",
        {
            "name": "Ravi Kumar",
            "phone": "98765 43210",
            "email": "ravi@example.com",
            "status": "new",
            "f_budget": "70 lakh",
            "f_location": "Baner, Pune",
            "f_bhk": "2 BHK",
            "f_timeline": "Within 30 days",
        },
    )
    assert response.status_code == 302
    lead = Lead.all_companies.get(company=realty)
    assert lead.reference == "LD-000001" and lead.phone == "+919876543210"
    assert lead.custom["budget"] == 700000000 and lead.custom["bhk"] == "2 BHK"
    # budget +10, timeline +20, location +10, bhk +10 = 50 → warm (hot ≥ 70)
    assert lead.score_value == 50 and lead.score_label == "warm"
    detail = owner.get(f"/app/leads/{lead.pk}/").content.decode()
    assert "₹70,00,000" in detail and "Baner, Pune" in detail
    dup = owner.post("/app/leads/new/", {"name": "Again", "phone": "+91 98765 43210", "status": "new"})
    assert dup.status_code == 200 and "already exists" in dup.content.decode()


@pytest.mark.django_db
def test_events_move_status_and_score(realty):
    lead = new_lead(realty, phone="+919811111111", custom={"budget": "1 cr", "timeline": "Within 30 days"})
    with company_context(realty.id):
        crm.apply_event(lead, "appointment_booked")
        lead.refresh_from_db()
        assert lead.status.key == "appointment" and lead.score_value == 70 and lead.score_label == "hot"
        crm.set_status(lead, "not_interested")
        lead.refresh_from_db()
        assert lead.score_label == "cold"  # forced label
        assert lead.score_events.count() >= 2


@pytest.mark.django_db
def test_new_template_field_appears_without_deployment(super_admin, owner, realty):
    """Phase 3 gate: a new CRM field added in Super Admin shows in the company's lead form after the update."""
    from apps.industries import services as templates

    admin_client = Client()
    admin_client.force_login(super_admin)

    draft = templates.create_draft(realty.industry)
    admin_client.post(
        f"/superadmin/templates/{draft.pk}/fields/new/",
        {
            "entity": "lead",
            "key": "loan_needed",
            "label": "Home Loan Needed",
            "type": "yes_no",
            "sort_order": 50,
            "is_active": "on",
        },
    )
    templates.publish(draft)
    assert b"Home Loan Needed" not in owner.get("/app/leads/new/").content
    owner.post("/app/template-update/")
    assert b"Home Loan Needed" in owner.get("/app/leads/new/").content


@pytest.mark.django_db
def test_company_custom_field_with_plan_limit(owner, realty):
    plan = Plan.objects.get(key="starter")
    PlanEntitlement.objects.create(plan=plan, key="custom_fields", limit_value=1)
    realty.plan = plan
    realty.save()
    owner.post(
        "/app/settings/crm/fields/new/",
        {"key": "referred_by", "label": "Referred By", "type": "text", "sort_order": 1, "is_active": "on"},
    )
    owner.post(
        "/app/settings/crm/fields/new/",
        {"key": "second", "label": "Second", "type": "text", "sort_order": 2, "is_active": "on"},
    )
    owner.post("/app/settings/crm/fields/new/", {"key": "budget", "label": "Clash", "type": "text", "sort_order": 3})
    assert list(FieldDefinition.objects.filter(company=realty).values_list("key", flat=True)) == ["referred_by"]
    assert b"Referred By" in owner.get("/app/leads/new/").content


@pytest.mark.django_db
def test_company_adjusts_a_scoring_rule(owner, realty):
    rule = ScoringRule.objects.get(template_version=realty.template_version, key="budget_given")
    owner.get(f"/app/settings/crm/scoring/new/?from={rule.pk}")
    mine = ScoringRule.objects.get(company=realty, key="budget_given")
    owner.post(
        f"/app/settings/crm/scoring/{mine.pk}/",
        {
            "key": "budget_given",
            "name": "Budget given",
            "kind": "field",
            "field": "budget",
            "op": "present",
            "points": 30,
            "priority": 0,
            "is_active": "on",
        },
    )
    lead = new_lead(realty, phone="+919822222222", custom={"budget": "50 lakh"})
    assert lead.score_value == 30


# ---------------------------------------------------------------- assignment (CRM-15)
@pytest.mark.django_db
def test_round_robin_and_rule_based_assignment(realty, owner_a, agent_a):
    AssignmentRule.all_companies.create(
        company=realty,
        name="Pune to agent",
        priority=0,
        strategy="user",
        condition={"field": "location", "op": "contains", "value": "pune"},
        targets=[str(agent_a.pk)],
    )
    AssignmentRule.all_companies.create(
        company=realty, name="Everyone", priority=1, strategy="round_robin", targets=[str(owner_a.pk), str(agent_a.pk)]
    )
    pune = new_lead(realty, phone="+919833333331", custom={"location": "Wakad, Pune"})
    first = new_lead(realty, phone="+919833333332", custom={"location": "Mumbai"})
    second = new_lead(realty, phone="+919833333333", custom={"location": "Delhi"})
    assert pune.assigned_user == agent_a
    assert {first.assigned_user, second.assigned_user} == {owner_a, agent_a}


# ---------------------------------------------------------------- list, filters, views, visibility (CRM-09)
@pytest.mark.django_db
def test_list_filters_saved_views_and_agent_visibility(owner, client, realty, agent_a, owner_a):
    new_lead(realty, name="Asha", phone="+919800000001", custom={"bhk": "2 BHK", "budget": "60 lakh"})
    new_lead(
        realty, name="Bilal", phone="+919800000002", custom={"bhk": "3 BHK", "budget": "1.5 cr"}, assigned_user=agent_a
    )
    html = owner.get("/app/leads/?cf_bhk=3+BHK").content.decode()
    assert "Bilal" in html and "Asha" not in html
    html = owner.get("/app/leads/?cf_budget_min=1+cr").content.decode()
    assert "Bilal" in html and "Asha" not in html
    assert "Asha" in owner.get("/app/leads/?q=9800000001").content.decode()
    owner.post("/app/leads/", {"op": "save_view", "name": "3 BHK", "params": "cf_bhk=3+BHK"})
    assert b"3 BHK" in owner.get("/app/leads/").content
    agent = Client()
    agent.force_login(agent_a)
    html = agent.get("/app/leads/").content.decode()
    assert "Bilal" in html and "Asha" not in html
    assert agent.get(f"/app/leads/{Lead.all_companies.get(name='Asha').pk}/").status_code == 404


@pytest.mark.django_db
def test_pipeline_move_and_detail_actions(owner, realty, owner_a):
    lead = new_lead(realty, phone="+919844444444")
    assert owner.get("/app/leads/board/").status_code == 200
    moved = owner.post(f"/app/leads/{lead.pk}/status/", {"status": "hot"}, HTTP_X_REQUESTED_WITH="fetch")
    assert moved.status_code == 204
    owner.post(f"/app/leads/{lead.pk}/", {"op": "note", "body": "Called, wants a site visit"})
    owner.post(f"/app/leads/{lead.pk}/", {"op": "follow_up", "when": "2030-01-05T10:00", "next_action": "Call back"})
    lead.refresh_from_db()
    assert lead.status.key == "hot" and lead.next_action == "Call back"
    task = Task.all_companies.get(lead=lead)
    assert task.assigned_user == owner_a
    owner.post(f"/app/leads/{lead.pk}/", {"op": "task_done", "task": task.pk})
    task.refresh_from_db()
    assert task.status == "done"
    types = set(LeadActivity.all_companies.filter(lead=lead).values_list("type", flat=True))
    assert {"created", "status_change", "note", "follow_up", "task"} <= types
    owner.post(f"/app/leads/{lead.pk}/", {"op": "delete"})
    assert b"(no name)" not in owner.get("/app/leads/").content and Lead.all_companies.get(pk=lead.pk).deleted_at
    owner.post(f"/app/leads/{lead.pk}/", {"op": "restore"})
    assert Lead.all_companies.get(pk=lead.pk).deleted_at is None


# ---------------------------------------------------------------- bulk, merge, export (CRM-13/14/17)
@pytest.mark.django_db
def test_bulk_actions_merge_and_export(owner, realty, agent_a):
    a = new_lead(realty, name="One", phone="+919855555551", email="same@example.com")
    b = new_lead(realty, name="Two", phone="+919855555552")
    ids = [a.pk, b.pk]
    owner.post("/app/leads/", {"op": "bulk", "action": "assign", "value": agent_a.pk, "ids": ids})
    owner.post("/app/leads/", {"op": "bulk", "action": "tag", "value": "vip", "ids": ids})
    owner.post("/app/leads/", {"op": "bulk", "action": "status", "value": "warm", "ids": ids})
    for lead in Lead.all_companies.filter(pk__in=ids):
        assert lead.assigned_user == agent_a and lead.tags == ["vip"] and lead.status.key == "warm"
    with company_context(realty.id):
        c = crm.create_lead(realty, {"name": "Three", "email": "same@example.com"}, allow_duplicate=True)
    groups = owner.get("/app/leads/duplicates/").content.decode()
    assert "same@example.com" in groups
    owner.post("/app/leads/duplicates/", {"primary": a.pk, "merge": [c.pk]})
    c.refresh_from_db()
    assert c.merged_into_id == a.pk and c.deleted_at
    export = owner.get("/app/leads/export/?format=csv")
    assert export.status_code == 200 and b"LD-000001" in export.content and b"Budget" in export.content
    xlsx = owner.get("/app/leads/export/?format=xlsx")
    assert xlsx.content[:2] == b"PK"
    assert AuditLog.objects.filter(action="lead.export").count() == 2
    camp = owner.post("/app/leads/", {"op": "bulk", "action": "add_to_campaign", "ids": ids}, follow=True)
    assert b"Choose a draft campaign" in camp.content  # no campaign chosen (Phase 6: tests/test_campaigns.py)


@pytest.mark.django_db
def test_agent_cannot_export_or_delete(client, agent_a, realty):
    client.force_login(agent_a)
    assert client.get("/app/leads/export/").status_code == 403
    assert client.get("/app/leads/duplicates/").status_code == 403


# ---------------------------------------------------------------- import gate (CRM-13)
@pytest.mark.django_db
def test_import_10000_rows_with_duplicates_and_errors(owner, realty):
    new_lead(realty, name="Existing", phone="+919700000005")
    buf = io.StringIO()
    buf.write("Full Name,Mobile,Email,BHK,Budget\n")
    for i in range(10_000):
        phone = f"97{i:08d}"
        if i % 1000 == 1:
            phone = "12"  # invalid
        if i % 1000 == 2:
            phone = f"97{i - 1:08d}"  # duplicate of the previous row (row i-1 is invalid → becomes unique)
        if i % 1000 == 3:
            phone = f"97{i - 3:08d}"  # duplicate of an earlier row in the file
        bhk = "9 BHK" if i % 2500 == 4 else "2 BHK"  # not an option → error
        buf.write(f"Lead {i},{phone},,{bhk},{50 + i % 50} lakh\n")
    upload = SimpleUploadedFile("leads.csv", buf.getvalue().encode(), content_type="text/csv")
    start = time.monotonic()
    owner.post("/app/leads/import/", {"file": upload})
    imp = LeadImport.all_companies.get(company=realty)
    assert imp.total == 10_000 and imp.mapping["Mobile"] == "phone" and imp.mapping["BHK"] == "custom:bhk"
    mapping = {f"map_{i}": t for i, t in enumerate(imp.mapping.get(h, "") for h in imp.headers)}
    owner.post(f"/app/leads/import/{imp.pk}/", {**mapping, "duplicate_mode": "skip"})
    imp.refresh_from_db()
    elapsed = time.monotonic() - start
    assert imp.failed == 10 + 4  # 10 invalid phones + 4 invalid BHK
    assert imp.skipped == 10 + 1  # 10 in-file duplicates + the existing lead (row of i=5)
    assert imp.created == 10_000 - imp.failed - imp.skipped
    assert Lead.all_companies.filter(company=realty, created_via="import").count() == imp.created
    numbers = set(Lead.all_companies.filter(company=realty).values_list("number", flat=True))
    assert len(numbers) == imp.created + 1
    report = owner.get(f"/app/leads/import/{imp.pk}/?report=1").content.decode()
    assert "Row,Reason" in report and "not a valid number" in report
    assert elapsed < 120, elapsed


@pytest.mark.django_db
def test_import_limits_and_excel(owner, realty, set_setting):
    set_setting("crm.import_max_rows", 10)
    rows = "Name,Phone\n" + "\n".join(f"P{i},98{i:08d}" for i in range(11))
    owner.post("/app/leads/import/", {"file": SimpleUploadedFile("big.csv", rows.encode())})
    assert not LeadImport.all_companies.filter(company=realty).exists()
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Name", "Phone"])
    wb.active.append(["Excel Lead", "9811122233"])
    data = io.BytesIO()
    wb.save(data)
    with company_context(realty.id):
        imp = imports.start(realty, SimpleUploadedFile("leads.xlsx", data.getvalue()))
        imports.run(imp, {"Name": "name", "Phone": "phone"})
    assert Lead.all_companies.get(name="Excel Lead").phone == "+919811122233"


# ---------------------------------------------------------------- tasks, reminders, search
@pytest.mark.django_db
def test_my_follow_ups_reminders_and_search(owner, realty, owner_a, mailoutbox):
    lead = new_lead(realty, name="Search Me", phone="+919866666666", email="find@example.com")
    with company_context(realty.id):
        crm.create_task(realty, {"lead": lead, "title": "Call today", "due_at": timezone.now()}, owner_a)
    assert b"Call today" in owner.get("/app/tasks/").content
    call_command("send_task_reminders")
    assert any("Call today" in m.subject for m in mailoutbox)
    for q in ("Search", "9866666666", "find@example", "LD-000001", "000001"):
        assert b"Search Me" in owner.get(f"/app/search/?q={q}").content, q


# ---------------------------------------------------------------- API + isolation
@pytest.mark.django_db
def test_crm_api_and_company_isolation(owner, realty, owner_b, company_b):
    created = owner.post(
        "/api/v1/crm/leads/",
        {"name": "Api Lead", "phone": "9877700000", "custom": {"bhk": "3 BHK"}},
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    lead_id = created.json()["id"]
    assert owner.post(f"/api/v1/crm/leads/{lead_id}/status/", {"status": "qualified"}).json()["status"] == "qualified"
    assert owner.post(f"/api/v1/crm/leads/{lead_id}/notes/", {"body": "hello"}).status_code == 201
    assert owner.get("/api/v1/crm/leads/?cf_bhk=3+BHK").json()["results"][0]["id"] == lead_id
    assert owner.get("/api/v1/crm/leads/search/?q=Api").json()[0]["id"] == lead_id
    timeline = owner.get(f"/api/v1/crm/leads/{lead_id}/timeline/").json()
    assert {"created", "status_change", "note"} <= {a["type"] for a in timeline}
    config = owner.get("/api/v1/crm/config/").json()
    assert "budget" in [f["key"] for f in config["lead_fields"]] and config["statuses"]
    dup = owner.post("/api/v1/crm/leads/", {"phone": "+919877700000"}, content_type="application/json")
    assert dup.status_code == 400 and dup.json()["error"]
    other = Client()
    other.force_login(owner_b)
    assert other.get(f"/api/v1/crm/leads/{lead_id}/").status_code == 404
    assert other.get("/api/v1/crm/leads/").json()["results"] == []
    assert other.post(f"/api/v1/crm/leads/{lead_id}/status/", {"status": "hot"}).status_code == 404


@pytest.mark.django_db
def test_crm_api_import_bulk_tasks(owner, realty, owner_a):
    upload = SimpleUploadedFile("a.csv", b"Name,Phone\nX,9800011111\nY,bad\n")
    started = owner.post("/api/v1/crm/imports/", {"file": upload}).json()
    done = owner.post(
        f"/api/v1/crm/imports/{started['id']}/",
        {"mapping": {"Name": "name", "Phone": "phone"}},
        content_type="application/json",
    ).json()
    assert done["created"] == 1 and done["failed"] == 1
    ids = [lead["id"] for lead in owner.get("/api/v1/crm/leads/").json()["results"]]
    assert owner.post(
        "/api/v1/crm/leads/bulk/", {"ids": ids, "action": "tag", "value": "api"}, content_type="application/json"
    ).json() == {"updated": 1}
    task = owner.post("/api/v1/crm/tasks/", {"lead": ids[0], "title": "Ring", "due_at": "2030-01-01T10:00:00Z"})
    assert task.status_code == 201
    assert owner.post(f"/api/v1/crm/tasks/{task.json()['id']}/complete/").json()["status"] == "done"
