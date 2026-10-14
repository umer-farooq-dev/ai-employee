"""Phase 2 website gate: every page renders from the CMS, changes show without deployment, enquiries, SEO."""

from pathlib import Path

import pytest
from django.conf import settings
from django.utils.html import escape

from apps.billing.models import Plan
from apps.cms import services as cms
from apps.cms.models import Page, Section
from apps.industries.models import Industry
from apps.website.models import Enquiry

PAGES = [
    "",
    "how-it-works",
    "ai-employees",
    "industries",
    "features",
    "pricing",
    "about",
    "contact",
    "faq",
    "terms",
    "privacy",
    "refund",
    "ai-usage",
]


@pytest.mark.django_db
@pytest.mark.parametrize("slug", PAGES)
def test_every_page_renders_its_cms_sections(client, slug):
    response = client.get(f"/{slug}/" if slug else "/")
    assert response.status_code == 200
    page = Page.objects.get(slug=slug)
    for section in page.sections.filter(is_visible=True):
        heading = section.content.get("heading")
        empty_list = "items" in section.content and not section.content["items"]  # FAQ / testimonials hide when empty
        if heading and not empty_list:
            assert escape(heading).encode() in response.content, (slug, section.section_type.key)


@pytest.mark.django_db
def test_super_admin_change_shows_without_deployment(client, super_admin):
    hero = Section.objects.get(page__key="home", section_type__key="hero")
    cms.save_draft(hero, {**hero.content, "heading": "Brand New Heading"}, super_admin)
    assert b"Brand New Heading" not in client.get("/").content  # drafts stay private
    cms.publish(hero, super_admin)
    assert b"Brand New Heading" in client.get("/").content
    cms.set_visibility(hero, False)
    assert b"Brand New Heading" not in client.get("/").content


@pytest.mark.django_db
def test_header_footer_and_branding_come_from_settings_and_cms(client, set_setting, super_admin):
    set_setting("general.platform_name", "Acme Workforce")
    header = Section.objects.get(page__key="site", section_type__key="header")
    cms.save_draft(header, {**header.content, "menu": [{"label": "Only Item", "url": "/faq/"}]}, super_admin)
    cms.publish(header, super_admin)
    html = client.get("/").content
    header = html.split(b"</header>")[0]
    assert b"Acme Workforce" in html and b"Only Item" in header and b"How It Works" not in header


@pytest.mark.django_db
def test_no_template_demo_text_left(client):
    """No hard-coded text from the purchased template (eSoft demo copy) remains on the site."""
    demo = [b"Quip", b"eSoft HR", b"Pat Cummins", b"Elementor", b"crypto", b"FOX tokens", b"281-789-6642"]
    for slug in PAGES:
        html = client.get(f"/{slug}/" if slug else "/").content
        assert not [d for d in demo if d in html], slug
    for path in Path(settings.BASE_DIR, "templates", "website").rglob("*.html"):
        text = path.read_text(encoding="utf8").encode()
        assert not [d for d in demo if d in text], path


@pytest.mark.django_db
def test_pricing_reads_plans_live(client):
    Plan.objects.filter(key="business").update(name="Growth Plan", price_monthly_paise=1234500)
    Plan.objects.filter(key="pro").update(is_public=False)
    html = client.get("/pricing/").content.decode()
    assert "Growth Plan" in html and "₹12,345" in html and '<span class="span">Pro</span>' not in html
    assert "/accounts/signup/?plan=starter" in html


@pytest.mark.django_db
def test_industry_pages_follow_super_admin(client):
    assert client.get("/industries/real-estate/").status_code == 200
    Industry.objects.filter(key="travel").update(is_active=False)
    assert client.get("/industries/travel/").status_code == 404
    assert b"/industries/travel/" not in client.get("/industries/").content


@pytest.mark.django_db
def test_enquiry_form_saves_and_notifies_team(client, set_setting, mailoutbox):
    set_setting("contact.team_notify_emails", ["sales@example.com"])
    data = {
        "name": "Ravi",
        "business_name": "Ravi Homes",
        "phone": "98765 43210",
        "email": "ravi@example.com",
        "industry": "real-estate",
        "message": "Need a demo",
        "next": "/contact/",
    }
    response = client.post("/enquiry/", data)
    assert response.status_code == 302 and "sent=1" in response.url
    enquiry = Enquiry.objects.get()
    assert enquiry.phone == "+919876543210" and enquiry.industry.key == "real-estate"
    assert mailoutbox[-1].to == ["sales@example.com"] and "Ravi Homes" in mailoutbox[-1].subject
    assert b"Thank you!" in client.get("/contact/?sent=1").content


@pytest.mark.django_db
def test_enquiry_spam_and_rate_limit(client, set_setting):
    base = {"name": "A", "business_name": "B", "phone": "9876543210", "email": "a@example.com", "industry": "travel"}
    client.post("/enquiry/", {**base, "company_website": "http://spam"})
    assert Enquiry.objects.count() == 0  # honeypot filled: silently dropped
    set_setting("security.api_rate_public_form", "2/hour")
    for _ in range(3):
        client.post("/enquiry/", base)
    assert Enquiry.objects.count() == 1  # the honeypot post used the first slot


@pytest.mark.django_db
def test_enquiry_open_redirect_is_blocked(client):
    response = client.post("/enquiry/", {"next": "//evil.example/"})
    assert response.url.startswith("/#") or response.url.startswith("/?")


@pytest.mark.django_db
def test_seo_robots_sitemap_and_structured_data(client, set_setting):
    html = client.get("/pricing/").content.decode()
    assert '<link rel="canonical"' in html and 'property="og:title"' in html and '"@type": "Organization"' in html
    sitemap = client.get("/sitemap.xml").content.decode()
    assert "/pricing/</loc>" in sitemap and "/industries/real-estate/</loc>" in sitemap and "_site" not in sitemap
    assert "Disallow: /superadmin/" in client.get("/robots.txt").content.decode()
    set_setting("seo.allow_indexing", False)
    assert client.get("/robots.txt").content.decode().strip().endswith("Disallow: /")
    assert b'content="noindex, nofollow"' in client.get("/").content


@pytest.mark.django_db
def test_accessibility_basics(client):
    html = client.get("/").content.decode()
    assert 'href="#main"' in html and 'id="main"' in html and "prefers-reduced-motion" in html
    assert html.count("<h1") == 1
