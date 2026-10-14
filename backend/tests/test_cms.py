"""WEB-04 / WEB-09 gate test: every website section editable and versioned; the content API returns what was saved."""

import pytest
from django.core.exceptions import ValidationError

from apps.cms import services as cms
from apps.cms.models import Page, Section, SectionType
from apps.cms.schemas import SECTION_TYPES


@pytest.mark.django_db
def test_every_template_section_has_a_section_type():
    keys = set(SectionType.objects.values_list("key", flat=True))
    assert keys == {t[0] for t in SECTION_TYPES}
    home = Page.objects.get(key="home")
    assert list(home.sections.values_list("section_type__key", flat=True)) == [
        "hero",
        "work",
        "counters",
        "features",
        "benefits",
        "solution",
        "testimonials",
        "pricing",
        "industries",
        "faq",
    ]
    assert set(Page.objects.get(key="site").sections.values_list("section_type__key", flat=True)) == {
        "header",
        "cta",
        "footer",
    }


@pytest.mark.django_db
def test_clean_content_follows_schema():
    hero = Section.objects.get(page__key="home", section_type__key="hero")
    cleaned = cms.clean_content(
        hero.section_type.schema,
        {
            "heading": "  Hire an AI Employee ",
            "evil": "<script>",
            "button": {"label": "Start", "url": "/register"},
            "floating_images": [{"image": "/a.png"}, {"image": ""}],
        },
    )
    assert cleaned["heading"] == "Hire an AI Employee" and "evil" not in cleaned
    assert cleaned["floating_images"] == [{"image": "/a.png"}]  # empty rows dropped
    counters = SectionType.objects.get(key="counters").schema
    with pytest.raises(ValidationError):
        cms.clean_content(counters, {"items": [{"number": "1", "label": str(i)} for i in range(5)]})  # max 4


@pytest.mark.django_db
def test_draft_publish_version_restore(super_admin, client):
    hero = Section.objects.get(page__key="home", section_type__key="hero")
    cms.save_draft(hero, {"heading": "Version one"}, super_admin)
    assert client.get("/public/v1/cms/home/").json()["sections"][0]["content"] == {}  # draft is not public
    cms.publish(hero, super_admin)
    cms.save_draft(hero, {"heading": "Version two"}, super_admin)
    cms.publish(hero, super_admin)
    data = client.get("/public/v1/cms/home/").json()
    assert data["sections"][0]["content"]["heading"] == "Version two"
    assert hero.versions.count() == 2
    cms.restore(hero, 1, super_admin)
    hero.refresh_from_db()
    assert hero.draft_content["heading"] == "Version one" and hero.content["heading"] == "Version two"


@pytest.mark.django_db
def test_visibility_and_order(super_admin, client):
    home = Page.objects.get(key="home")
    faq = home.sections.get(section_type__key="faq")
    cms.set_visibility(faq, False)
    assert "faq" not in [s["type"] for s in client.get("/public/v1/cms/home/").json()["sections"]]
    ids = [str(i) for i in home.sections.values_list("id", flat=True)]
    cms.reorder(home, list(reversed(ids)))
    assert str(home.sections.first().id) == ids[-1]
    with pytest.raises(ValidationError):
        cms.reorder(home, ids[:2])


@pytest.mark.django_db
def test_section_editor_and_api(admin_client, client):
    section = Section.objects.get(page__key="home", section_type__key="counters")
    response = admin_client.post(
        f"/superadmin/website/sections/{section.pk}/",
        {
            "op": "publish",
            "l.items.0.number": "500",
            "l.items.0.suffix": "+",
            "l.items.0.label": "Businesses",
            "l.items.7.number": "24",
            "l.items.7.suffix": "/7",
            "l.items.7.label": "Always on",
        },
    )
    assert response.status_code == 302
    section.refresh_from_db()
    assert section.content["items"][1] == {"number": "24", "suffix": "/7", "label": "Always on"}
    api = admin_client.put(
        f"/api/v1/admin/cms/sections/{section.pk}/draft/",
        {"content": {"items": [{"number": "1", "suffix": "", "label": "x"}]}},
        content_type="application/json",
    )
    assert api.status_code == 200 and api.json()["has_draft"]
    assert admin_client.post(f"/api/v1/admin/cms/sections/{section.pk}/publish/").json()["version"] == 2
    assert client.get("/public/v1/cms/home/").json()["sections"][2]["content"]["items"][0]["label"] == "x"
