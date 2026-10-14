"""SA-01 …: every Super Admin screen renders on the Rizz template; key forms work; Django admin does not exist."""

import pytest
from django.core import mail
from django.urls import reverse

from apps.billing.models import Plan
from apps.cms.models import Page, Section
from apps.notifications.models import EmailTemplate
from apps.rbac.models import Role
from apps.tenancy.models import Company


@pytest.mark.django_db
def test_every_screen_renders(admin_client, owner_a, company_a):
    plan = Plan.objects.first()
    names = [
        "dashboard",
        "company_list",
        "company_create",
        "user_list",
        "user_create",
        "role_list",
        "role_create",
        "plan_list",
        "plan_create",
        "general_settings",
        "system_settings",
        "cms_pages",
        "email_template_list",
        "logs",
        "sessions",
    ]
    urls = [reverse(f"superadmin:{n}") for n in names] + [
        reverse("superadmin:company_detail", args=[company_a.pk]),
        reverse("superadmin:company_edit", args=[company_a.pk]),
        reverse("superadmin:user_detail", args=[owner_a.pk]),
        reverse("superadmin:plan_edit", args=[plan.pk]),
        reverse("superadmin:role_edit", args=[Role.objects.first().pk]),
        reverse("superadmin:cms_page", args=[Page.objects.get(key="home").pk]),
        reverse("superadmin:cms_section", args=[Section.objects.filter(page__key="home").first().pk]),
        reverse("superadmin:email_template_edit", args=[EmailTemplate.objects.first().pk]),
        reverse("superadmin:logs_kind", args=["security"]),
        reverse("superadmin:logs_kind", args=["api"]),
        reverse("superadmin:logs_kind", args=["errors"]),
        "/profile/",
        "/accounts/2fa/",
        "/accounts/sessions/",
    ]
    for tab in ("branding", "contact", "locale", "seo_email", "maintenance"):
        urls.append(reverse("superadmin:general_settings") + f"?tab={tab}")
    for url in urls:
        response = admin_client.get(url)
        assert response.status_code == 200, url
        assert b"startbar" in response.content or b"auth-header-box" in response.content, url  # Rizz layout


@pytest.mark.django_db
def test_no_django_admin_url(client):
    assert client.get("/admin/").status_code == 404


@pytest.mark.django_db
def test_create_company_with_owner(admin_client):
    response = admin_client.post(
        reverse("superadmin:company_create"),
        {"name": "Gamma Homes", "plan": Plan.objects.get(key="pro").pk, "owner_email": "owner@gamma.example"},
    )
    company = Company.objects.get(name="Gamma Homes")
    assert response.url == reverse("superadmin:company_detail", args=[company.pk])
    assert company.plan.key == "pro" and company.slug == "gamma-homes"


@pytest.mark.django_db
def test_create_staff_user_sends_set_password_email(admin_client):
    admin_client.post(
        reverse("superadmin:user_create"),
        {
            "email": "ops@example.com",
            "full_name": "Ops",
            "is_staff": "on",
            "platform_role": Role.objects.get(key="support").pk,
        },
    )
    assert mail.outbox and mail.outbox[-1].to == ["ops@example.com"]
    assert "password" in mail.outbox[-1].subject.lower()


@pytest.mark.django_db
def test_plan_form_saves_prices_and_limits(admin_client):
    plan = Plan.objects.get(key="starter")
    admin_client.post(
        reverse("superadmin:plan_edit", args=[plan.pk]),
        {
            "name": "Starter",
            "price_monthly": "3499",
            "status": "active",
            "sort_order": 1,
            "is_public": "on",
            "features_text": "1 AI Employee\nHindi + English",
            "limit__ai_employees": 1,
            "limit__voice_minutes": 500,
        },
    )
    plan.refresh_from_db()
    assert plan.price_monthly_paise == 349900 and plan.features == ["1 AI Employee", "Hindi + English"]
    assert plan.entitlements.get(key="ai_employees").limit_value == 1


@pytest.mark.django_db
def test_role_permissions_editable(admin_client):
    role = Role.objects.get(key="support")
    admin_client.post(
        reverse("superadmin:role_edit", args=[role.pk]),
        {"name": "Support", "description": "", "permissions": ["dashboard.view", "logs.view"]},
    )
    role.refresh_from_db()
    assert role.permissions == ["dashboard.view", "logs.view"]


@pytest.mark.django_db
def test_password_reset_uses_database_template(client, owner_a, set_setting):
    set_setting("general.platform_name", "Sara AI")
    set_setting("email.sender_name", "Sara Team")
    tpl = EmailTemplate.objects.get(key="account/email/password_reset_key")
    tpl.subject = "Reset for {{ platform_name }}"
    tpl.save()
    client.post("/accounts/password/reset/", {"email": owner_a.email})
    message = mail.outbox[-1]
    assert message.subject == "Reset for Sara AI" and message.from_email.startswith("Sara Team")
