"""Phase 3 part 3: catalogues (CAT-01, CAT-02, CAT-04 … CAT-08) — panel and API, with company isolation."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.catalog.models import CatalogCollection, CatalogItem, CatalogMedia, CollectionItem
from apps.industries import services as templates
from apps.industries.models import Industry
from apps.rbac.models import Role
from apps.tenancy.services import add_member

from .conftest import make_user

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


PROPERTY = {
    "status": "active",
    "f_project_name": "Green Valley",
    "f_builder": "Acme",
    "f_location": "Baner, Pune",
    "f_property_type": "Apartment",
    "f_bhk": "2 BHK",
    "f_price": "70 lakh",
    "f_availability": "Available",
}


@pytest.mark.django_db
def test_property_item_with_indian_price(owner, realty):
    response = owner.post("/app/catalogue/property/new/", PROPERTY)
    assert response.status_code == 302
    item = CatalogItem.all_companies.get(company=realty)
    assert item.title == "Green Valley" and item.price_paise == 700000000
    html = owner.get("/app/catalogue/property/").content.decode()
    assert "₹70,00,000" in html and "₹70 Lakh" in html
    bad = owner.post("/app/catalogue/property/new/", {**PROPERTY, "f_price": "", "f_project_name": ""})
    assert bad.status_code == 200 and not CatalogItem.all_companies.filter(title="").exists()


@pytest.mark.django_db
def test_filters_bulk_edit_and_collections(owner, realty):
    owner.post("/app/catalogue/property/new/", PROPERTY)
    owner.post(
        "/app/catalogue/property/new/",
        {**PROPERTY, "f_project_name": "Sky Towers", "f_bhk": "3 BHK", "f_price": "1.5 cr"},
    )
    html = owner.get("/app/catalogue/property/?f_bhk=3+BHK").content.decode()
    assert "Sky Towers" in html and "Green Valley" not in html
    html = owner.get("/app/catalogue/property/?f_price_max=1+cr").content.decode()
    assert "Green Valley" in html and "Sky Towers" not in html
    ids = list(CatalogItem.all_companies.filter(company=realty).values_list("pk", flat=True))
    owner.post("/app/catalogue/property/", {"ids": ids, "field": "availability", "value": "Few units left"})
    owner.post("/app/catalogue/property/", {"ids": ids[:1], "field": "status", "value": "inactive"})
    items = CatalogItem.all_companies.filter(company=realty)
    assert {i.attributes["availability"] for i in items} == {"Few units left"}
    assert items.filter(status="inactive").count() == 1
    owner.post(
        "/app/catalogue/property/collections/new/",
        {"name": "Under 1 Cr", "mode": "filter", "filter": "f_price_max=1+cr"},
    )
    owner.post(
        "/app/catalogue/property/collections/new/", {"name": "Hand picked", "mode": "manual", "items": [str(ids[1])]}
    )
    by_filter = CatalogCollection.all_companies.get(name="Under 1 Cr")
    manual = CatalogCollection.all_companies.get(name="Hand picked")
    assert b"Green Valley" in owner.get(f"/app/catalogue/property/collections/{by_filter.pk}/").content
    assert CollectionItem.all_companies.filter(collection=manual).count() == 1


@pytest.mark.django_db
def test_media_upload_is_private_and_signed(owner, realty):
    owner.post("/app/catalogue/property/new/", PROPERTY)
    item = CatalogItem.all_companies.get(company=realty)
    owner.post(
        f"/app/catalogue/property/{item.pk}/",
        {"op": "media", "kind": "photo", "files": [SimpleUploadedFile("front.png", PNG)]},
    )
    media = CatalogMedia.all_companies.get(item=item)
    assert media.file_key.startswith(f"tenants/{realty.id}/catalog/")
    page = owner.get(f"/app/catalogue/property/{item.pk}/").content.decode()
    link = "/files/" + page.split('src="/files/')[1].split('"')[0]
    assert link.startswith("/files/") and Client().get(link).status_code == 200
    owner.post(
        f"/app/catalogue/property/{item.pk}/",
        {"op": "media", "kind": "photo", "files": [SimpleUploadedFile("evil.exe", b"MZ")]},
    )
    assert CatalogMedia.all_companies.filter(item=item).count() == 1


@pytest.mark.django_db
def test_new_catalogue_field_from_super_admin_without_deployment(super_admin, owner, realty):
    """Phase 3 gate: a new catalogue field added in Super Admin appears for the company after the update."""
    admin = Client()
    admin.force_login(super_admin)
    draft = templates.create_draft(realty.industry)
    admin.post(
        f"/superadmin/templates/{draft.pk}/fields/new/",
        {
            "entity": "catalog:property",
            "key": "rera_number",
            "label": "RERA Number",
            "type": "text",
            "sort_order": 99,
            "is_active": "on",
        },
    )
    templates.publish(draft)
    owner.post("/app/template-update/")
    assert b"RERA Number" in owner.get("/app/catalogue/property/new/").content


@pytest.mark.django_db
def test_import_properties(owner, realty):
    csv = (
        "Project Name,Location,Price,BHK\nAlpha Homes,Wakad,85 lakh,2 BHK\nBeta,Hinjewadi,abc,2 BHK\n"
        "Gamma,Aundh,1.2 Cr,9 BHK\n"
    )
    owner.post("/app/catalogue/property/import/", {"file": SimpleUploadedFile("p.csv", csv.encode())})
    from apps.catalog.models import CatalogImport

    imp = CatalogImport.all_companies.get(company=realty)
    assert imp.mapping["Price"] == "price"
    owner.post(
        f"/app/catalogue/property/import/{imp.pk}/", {f"map_{i}": imp.mapping[h] for i, h in enumerate(imp.headers)}
    )
    imp.refresh_from_db()
    assert imp.created == 1 and imp.failed == 2
    assert CatalogItem.all_companies.get(title="Alpha Homes").price_paise == 850000000  # ₹85,00,000


@pytest.mark.django_db
def test_travel_and_education_catalogues(client, company_b, owner_b):
    for key, catalog_key, data in (
        ("travel", "travel_package", {"package_name": "Goa 3N", "destinations": "Goa", "price_per_person": "18,500"}),
        ("education", "course", {"course_name": "MBA", "institution": "ABC College", "fees": "4.5 lakh"}),
    ):
        industry = Industry.objects.get(key=key)
        company_b.industry, company_b.template_version = industry, industry.published_version
        company_b.save()
        client.force_login(owner_b)
        response = client.post(
            "/api/v1/catalog/items/", {"type": catalog_key, "attributes": data}, content_type="application/json"
        )
        assert response.status_code == 201, response.content
        assert response.json()["price"]["formatted"] in ("₹18,500", "₹4,50,000")


@pytest.mark.django_db
def test_catalog_api_and_isolation(owner, realty, owner_b, company_b):
    types = owner.get("/api/v1/catalog/types/").json()
    assert types[0]["key"] == "property" and "price" in [f["key"] for f in types[0]["fields"]]
    created = owner.post(
        "/api/v1/catalog/items/",
        {
            "type": "property",
            "attributes": {"project_name": "Api Tower", "location": "Pune", "price": "95 lakh", "bhk": "3 BHK"},
        },
        content_type="application/json",
    ).json()
    assert created["price"]["short"] == "₹95 Lakh"
    assert owner.get("/api/v1/catalog/items/?type=property&f_bhk=3+BHK").json()["results"][0]["id"] == created["id"]
    media = owner.post(f"/api/v1/catalog/items/{created['id']}/media/", {"file": SimpleUploadedFile("a.png", PNG)})
    assert media.status_code == 201 and media.json()["url"].startswith("/files/")
    col = owner.post(
        "/api/v1/catalog/collections/",
        {"type": "property", "name": "API", "items": [created["id"]]},
        content_type="application/json",
    ).json()
    assert col["item_ids"] == [created["id"]]
    assert owner.post(
        "/api/v1/catalog/items/bulk/",
        {"ids": [created["id"]], "field": "status", "value": "inactive"},
        content_type="application/json",
    ).json() == {"updated": 1}
    upload = SimpleUploadedFile("x.csv", b"Project Name,Location,Price\nImp,Pune,50 lakh\n")
    imp = owner.post("/api/v1/catalog/imports/", {"type": "property", "file": upload}).json()
    done = owner.post(
        f"/api/v1/catalog/imports/{imp['id']}/", {"mapping": imp["mapping"]}, content_type="application/json"
    ).json()
    assert done["created"] == 1
    other = Client()
    other.force_login(owner_b)
    assert other.get(f"/api/v1/catalog/items/{created['id']}/").status_code == 404
    assert other.get("/api/v1/catalog/collections/").json() == []


@pytest.mark.django_db
def test_agent_can_view_but_not_manage(client, realty):
    agent = make_user("agent2@alpha.example")
    add_member(realty, agent.email, Role.objects.get(scope="company", key="agent"))
    client.force_login(agent)
    assert client.get("/app/catalogue/property/").status_code == 200
    assert client.get("/app/catalogue/property/new/").status_code == 403
    assert (
        client.post("/api/v1/catalog/items/", {"type": "property"}, content_type="application/json").status_code == 403
    )
