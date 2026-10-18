"""Phase 3 part 1: industry template engine (IND-01 … IND-06, ROLE-01, SA-05, SA-07), field engine, INR (CAT-08)."""

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.core.money import format_inr, format_inr_short, parse_inr
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.industries.models import (
    AppointmentType,
    CatalogType,
    FieldDefinition,
    Industry,
    LeadSource,
    LeadStatus,
    TemplateVersion,
)
from apps.roles_tools.models import EmployeeRole


@pytest.fixture
def real_estate(db):
    return Industry.objects.get(key="real-estate")


# ---------------------------------------------------------------- seeds (IND-06, CRM-02/03/05/06/07, CAT-02/05/06)
@pytest.mark.django_db
def test_mvp_templates_are_seeded_and_published():
    expected = {
        "real-estate": (
            {"budget", "location", "bhk", "property_type", "purpose", "site_visit"},
            "property",
            {
                "project_name",
                "builder",
                "location",
                "address",
                "property_type",
                "bhk",
                "price",
                "area",
                "floor",
                "possession",
                "amenities",
                "description",
                "availability",
                "booking_status",
            },
            "site_visit",
        ),
        "travel": (
            {"destination", "travel_date", "passengers", "budget", "package"},
            "travel_package",
            {
                "package_name",
                "destinations",
                "duration_days",
                "duration_nights",
                "price_per_person",
                "inclusions",
                "exclusions",
                "itinerary",
                "available_dates",
            },
            "travel_consultation",
        ),
        "education": (
            {"course", "qualification", "preferred_college", "admission_requirement"},
            "course",
            {
                "course_name",
                "institution",
                "eligibility",
                "fees",
                "duration",
                "intake_dates",
                "seats",
                "mode",
                "description",
            },
            "counselling_session",
        ),
    }
    for key, (lead_keys, catalog_key, catalog_keys, appt_key) in expected.items():
        version = Industry.objects.get(key=key).published_version
        assert version and version.status == TemplateVersion.PUBLISHED
        assert lead_keys <= set(
            FieldDefinition.objects.filter(template_version=version, entity="lead").values_list("key", flat=True)
        )
        catalog = CatalogType.objects.get(template_version=version)
        assert catalog.key == catalog_key
        assert catalog_keys == set(
            FieldDefinition.objects.filter(template_version=version, entity=catalog.entity).values_list(
                "key", flat=True
            )
        )
        assert AppointmentType.objects.get(template_version=version).key == appt_key
        assert version.greetings.keys() >= {"en", "hi", "bn"} and version.qualification_flow
    statuses = list(
        LeadStatus.objects.filter(template_version__isnull=True, company__isnull=True).values_list("key", flat=True)
    )
    assert statuses == [
        "new",
        "calling",
        "connected",
        "qualified",
        "hot",
        "warm",
        "cold",
        "follow_up",
        "appointment",
        "converted",
        "not_interested",
    ]
    assert set(LeadSource.objects.values_list("key", flat=True)) == {
        "inbound_call",
        "outbound_campaign",
        "whatsapp",
        "website_chat",
        "manual",
        "import",
    }
    assert EmployeeRole.objects.count() == 5  # Phase 4 adds the Follow-up Employee (ROLE-05)


# ---------------------------------------------------------------- field engine + INR
def test_inr_formats_and_parsing():
    assert format_inr(700000000) == "₹70,00,000"
    assert format_inr_short(700000000) == "₹70 Lakh" and format_inr_short(1200000000) == "₹1.2 Cr"
    assert parse_inr("70 lakh") == parse_inr("70,00,000") == parse_inr("₹7000000") == 700000000
    assert parse_inr("1.2 Cr") == 1200000000
    with pytest.raises(ValidationError):
        parse_inr("seventy")


@pytest.mark.django_db
def test_field_engine_validates_every_type():
    def d(type, **kw):
        return FieldDefinition(key="x", label="X", type=type, **kw)

    assert field_engine.clean_value(d("currency"), "70 lakh") == 700000000
    assert field_engine.clean_value(d("number"), "1,200") == 1200
    assert field_engine.clean_value(d("date"), "2026-11-08") == "2026-11-08"
    assert field_engine.clean_value(d("yes_no"), "yes") is True
    assert field_engine.clean_value(d("phone"), "98765 43210") == "+919876543210"
    assert field_engine.clean_value(d("single_select", options=["2 BHK", "3 BHK"]), "2 bhk") == "2 BHK"
    assert field_engine.clean_value(d("multi_select", options=["Gym", "Lift"]), "Gym, Lift") == ["Gym", "Lift"]
    for bad in [
        (d("email"), "nope"),
        (d("single_select", options=["A"]), "B"),
        (d("number"), "abc"),
        (d("text", required=True), ""),
        (d("number", validation={"min": 1}), "0"),
    ]:
        with pytest.raises(ValidationError):
            field_engine.clean_value(*bad)


# ---------------------------------------------------------------- versioning gate (IND-03)
@pytest.mark.django_db
def test_publish_upgrade_and_rollback(admin_client, real_estate, owner_a, company_a):
    from django.test import Client

    client = Client()
    v1 = real_estate.published_version
    company_a.industry, company_a.template_version = real_estate, v1
    company_a.save()

    admin_client.post(f"/superadmin/industries/{real_estate.pk}/templates/", {"op": "draft"})
    v2 = real_estate.versions.get(status="draft")
    assert (
        FieldDefinition.objects.filter(template_version=v2).count()
        == FieldDefinition.objects.filter(template_version=v1).count()
    )
    # Add a new CRM field from Super Admin — no deployment
    admin_client.post(
        f"/superadmin/templates/{v2.pk}/fields/new/",
        {
            "entity": "lead",
            "key": "loan_needed",
            "label": "Home Loan Needed",
            "type": "yes_no",
            "sort_order": 50,
            "is_active": "on",
        },
    )
    assert FieldDefinition.objects.filter(template_version=v2, key="loan_needed").exists()
    admin_client.post(f"/superadmin/industries/{real_estate.pk}/templates/", {"op": "publish", "version": v2.pk})
    real_estate.refresh_from_db()
    v1.refresh_from_db()
    assert real_estate.published_version == v2 and v1.status == "archived"

    company_a.refresh_from_db()
    assert company_a.template_version == v1  # stays until accepted
    assert "loan_needed" not in [f.key for f in templates.fields_for(company_a)]
    client.force_login(owner_a)
    assert b"Update available" in client.get("/app/").content
    client.post("/app/template-update/")
    company_a.refresh_from_db()
    assert company_a.template_version == v2 and "loan_needed" in [f.key for f in templates.fields_for(company_a)]

    # Roll back: republish v1 and move the company back
    admin_client.post(f"/superadmin/industries/{real_estate.pk}/templates/", {"op": "publish", "version": v1.pk})
    admin_client.post(f"/superadmin/companies/{company_a.pk}/template/", {"version": v1.pk})
    real_estate.refresh_from_db()
    company_a.refresh_from_db()
    assert real_estate.published_version == v1 and company_a.template_version == v1


@pytest.mark.django_db
def test_published_versions_are_read_only(admin_client, real_estate):
    v1 = real_estate.published_version
    field = FieldDefinition.objects.filter(template_version=v1).first()
    admin_client.post(
        f"/superadmin/templates/{v1.pk}/fields/{field.pk}/",
        {"entity": "lead", "key": field.key, "label": "Changed", "type": field.type},
    )
    field.refresh_from_db()
    assert field.label != "Changed"
    api = admin_client.patch(f"/api/v1/admin/templates/{v1.pk}/", {"notes": "x"}, content_type="application/json")
    assert api.status_code == 400
    assert admin_client.post(f"/superadmin/industries/{real_estate.pk}/templates/", {"op": "draft"}).status_code == 302
    assert admin_client.post("/api/v1/admin/templates/", {"industry": real_estate.pk}).status_code == 400  # one draft


@pytest.mark.django_db
def test_general_editor_saves_and_validates(admin_client, real_estate):
    draft = templates.create_draft(real_estate)
    post = {
        "notes": "Hinglish greeting",
        "f.base_instructions": "Be kind",
        "f.greeting_en": "Hi there",
        "f.greeting_hi": "नमस्ते",
        "f.hot_threshold": "80",
        "f.warm_threshold": "50",
        "l.qualification_flow.0.field": "budget",
        "l.qualification_flow.0.question_en": "Budget?",
        "l.status_transitions.0.event": "appointment_booked",
        "l.status_transitions.0.status": "appointment",
    }
    admin_client.post(f"/superadmin/templates/{draft.pk}/", post)
    draft.refresh_from_db()
    assert draft.greetings == {"en": "Hi there", "hi": "नमस्ते"} and draft.score_thresholds == {"hot": 80, "warm": 50}
    assert draft.qualification_flow == [{"field": "budget", "question": {"en": "Budget?"}}]
    admin_client.post(f"/superadmin/templates/{draft.pk}/", {**post, "f.warm_threshold": "90"})
    draft.refresh_from_db()
    assert draft.score_thresholds["warm"] == 50  # warm ≥ hot rejected


@pytest.mark.django_db
def test_clone_industry_and_activation(admin_client, client, real_estate):
    admin_client.post(
        f"/superadmin/industries/{real_estate.pk}/templates/",
        {"op": "clone", "name": "Commercial Real Estate", "key": "commercial"},
    )
    clone = Industry.objects.get(key="commercial")
    assert not clone.is_active and clone.versions.get().status == "draft"
    assert (
        FieldDefinition.objects.filter(template_version__industry=clone).count()
        == FieldDefinition.objects.filter(template_version=real_estate.published_version).count()
    )
    keys = [i["key"] for i in client.get("/public/v1/registration-options/").json()["industries"]]
    assert "commercial" not in keys  # IND-04 inactive → hidden from registration


@pytest.mark.django_db
def test_template_api_draft_child_publish(admin_client, real_estate):
    draft = admin_client.post("/api/v1/admin/templates/", {"industry": real_estate.pk}).json()
    created = admin_client.post(
        "/api/v1/admin/template-fields/",
        {"template_version": draft["id"], "entity": "lead", "key": "parking", "label": "Parking", "type": "yes_no"},
        content_type="application/json",
    )
    assert created.status_code == 201
    assert admin_client.post(f"/api/v1/admin/templates/{draft['id']}/publish/").json()["status"] == "published"
    blocked = admin_client.post(
        "/api/v1/admin/template-fields/",
        {"template_version": draft["id"], "entity": "lead", "key": "x2", "label": "X", "type": "text"},
        content_type="application/json",
    )
    assert blocked.status_code == 400


@pytest.mark.django_db
def test_super_admin_crm_config_roles_and_holidays_screens(admin_client, support, client):
    for url in (
        "/superadmin/crm/statuses/",
        "/superadmin/crm/sources/",
        "/superadmin/holidays/",
        "/superadmin/employee-roles/",
        "/superadmin/platform/employee-roles/new/",
    ):
        assert admin_client.get(url).status_code == 200, url
    admin_client.post("/superadmin/platform/holidays/new/", {"date": "2027-01-26", "name": "Republic Day"})
    admin_client.post(
        "/superadmin/platform/sources/new/",
        {"key": "referral", "label": "Referral", "is_active": "on", "sort_order": 9},
    )
    assert LeadSource.objects.filter(key="referral").exists()
    new = LeadStatus.objects.get(key="new", template_version__isnull=True)
    admin_client.post(f"/superadmin/platform/statuses/{new.pk}/", {"op": "delete"})
    assert LeadStatus.objects.filter(pk=new.pk).exists()  # seeded statuses cannot be deleted
    client.force_login(support)
    assert client.get("/superadmin/crm/statuses/").status_code == 403


@pytest.mark.django_db
def test_company_rows_are_isolated_and_platform_rows_read_only(company_a, company_b, real_estate):
    """RLS on template tables: companies read platform rows, only their own rows, and never write platform rows."""
    from django.core.management import call_command
    from django.db import DatabaseError, transaction

    version = real_estate.published_version
    FieldDefinition.objects.create(company=company_a, entity="lead", key="a_only", label="A")
    FieldDefinition.objects.create(company=company_b, entity="lead", key="b_only", label="B")
    platform_rows = FieldDefinition.objects.filter(company__isnull=True).count()
    call_command("setup_app_db_role", role="rls_probe2")
    with connection.cursor() as cur:
        cur.execute("SET ROLE rls_probe2")
        try:
            cur.execute(
                "SELECT set_config('app.company_id', %s, true), set_config('app.bypass_rls', '', true)",
                [str(company_a.id)],
            )
            cur.execute("SELECT count(*) FROM industries_fielddefinition")
            assert cur.fetchone()[0] == platform_rows + 1
            cur.execute("SELECT count(*) FROM industries_fielddefinition WHERE key = 'b_only'")
            assert cur.fetchone()[0] == 0
            with pytest.raises(DatabaseError), transaction.atomic():
                cur.execute(
                    "UPDATE industries_fielddefinition SET label = 'hack' WHERE template_version_id = %s RETURNING id",
                    [str(version.id)],
                )
                assert cur.fetchone() is None
                raise DatabaseError("no platform row was writable")
        finally:
            cur.execute("RESET ROLE")


@pytest.mark.django_db
def test_template_screens_render(admin_client, real_estate):
    v1 = real_estate.published_version
    assert admin_client.get("/superadmin/industries/").status_code == 200
    assert admin_client.get(f"/superadmin/industries/{real_estate.pk}/templates/").status_code == 200
    for tab in ("general", "fields", "catalogue", "appointments", "statuses", "scoring"):
        assert admin_client.get(f"/superadmin/templates/{v1.pk}/?tab={tab}").status_code == 200, tab
    for kind, model in (
        ("fields", FieldDefinition),
        ("catalog-types", CatalogType),
        ("appointment-types", AppointmentType),
    ):
        item = model.objects.filter(template_version=v1).first()
        assert admin_client.get(f"/superadmin/templates/{v1.pk}/{kind}/{item.pk}/").status_code == 200
    rule = v1.scoringrule_set.first()
    assert admin_client.get(f"/superadmin/templates/{v1.pk}/scoring/{rule.pk}/").status_code == 200
