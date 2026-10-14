"""AUTH-07 team, AUTH-09 profile, CP-06 hours, AUTH-10 onboarding, CP-01/02 panel shell (web, API, isolation)."""

import re

import pytest
from django.test import Client

from apps.billing.models import PlanEntitlement
from apps.rbac.models import Role
from apps.tenancy.models import Invitation, Membership
from apps.tenancy.services import add_member

from .conftest import PASSWORD, make_user


def invite_link(mailoutbox):
    return re.search(r"/invite/[\w-]+/", mailoutbox[-1].alternatives[0][0]).group(0)


@pytest.fixture
def owner_client(client, owner_a):
    client.force_login(owner_a)
    return client


@pytest.fixture
def manager_a(company_a):
    user = make_user("manager@alpha.example")
    add_member(company_a, user.email, Role.objects.get(scope="company", key="manager"))
    return user


@pytest.mark.django_db
def test_invite_and_accept_as_new_user(owner_client, company_a, mailoutbox):
    response = owner_client.post(
        "/app/team/", {"op": "invite", "email": "New@Alpha.example", "role": Role.objects.get(key="agent").pk}
    )
    assert response.status_code == 302
    invitation = Invitation.all_companies.get(company=company_a)
    assert invitation.email == "new@alpha.example" and len(invitation.token_hash) == 64
    link = invite_link(mailoutbox)
    visitor = Client()
    assert b"Join Alpha Realty" in visitor.get(link).content
    visitor.post(link, {"full_name": "Neha", "password1": PASSWORD, "password2": PASSWORD})
    membership = Membership.all_companies.get(company=company_a, user__email="new@alpha.example")
    assert membership.role.key == "agent" and membership.status == Membership.ACTIVE
    assert visitor.get("/app/").status_code == 200
    assert b"no longer valid" in Client().get(link).content  # single use


@pytest.mark.django_db
def test_existing_user_must_use_invited_email(owner_client, owner_b, mailoutbox):
    owner_client.post(
        "/app/team/", {"op": "invite", "email": "someone@else.example", "role": Role.objects.get(key="agent").pk}
    )
    other = Client()
    other.force_login(owner_b)
    other.post(invite_link(mailoutbox))
    assert Invitation.all_companies.get().status == Invitation.PENDING


@pytest.mark.django_db
def test_seat_limit_from_plan(owner_client, company_a):
    from apps.billing.models import Plan

    plan = Plan.objects.get(key="starter")
    PlanEntitlement.objects.create(plan=plan, key="users", limit_value=2)
    company_a.plan = plan
    company_a.save()
    agent = Role.objects.get(key="agent").pk
    owner_client.post("/app/team/", {"op": "invite", "email": "one@alpha.example", "role": agent})
    owner_client.post("/app/team/", {"op": "invite", "email": "two@alpha.example", "role": agent})
    assert Invitation.all_companies.filter(company=company_a).count() == 1  # owner + 1 invite = 2 seats


@pytest.mark.django_db
def test_resend_cancel_role_deactivate_and_owner_protection(owner_client, owner_a, manager_a, company_a, mailoutbox):
    owner_client.post(
        "/app/team/", {"op": "invite", "email": "x@alpha.example", "role": Role.objects.get(key="agent").pk}
    )
    invitation = Invitation.all_companies.get()
    old = invitation.token_hash
    owner_client.post("/app/team/", {"op": "resend", "invitation": invitation.pk})
    invitation.refresh_from_db()
    assert invitation.token_hash != old and len(mailoutbox) == 2
    owner_client.post("/app/team/", {"op": "cancel", "invitation": invitation.pk})
    invitation.refresh_from_db()
    assert invitation.status == Invitation.CANCELLED

    m = Membership.all_companies.get(user=manager_a)
    owner_client.post("/app/team/", {"op": "role", "member": m.pk, "role": Role.objects.get(key="agent").pk})
    owner_client.post("/app/team/", {"op": "deactivate", "member": m.pk})
    m.refresh_from_db()
    assert m.role.key == "agent" and m.status == Membership.DISABLED
    own = Membership.all_companies.get(user=owner_a)
    owner_client.post("/app/team/", {"op": "deactivate", "member": own.pk})
    own.refresh_from_db()
    assert own.status == Membership.ACTIVE


@pytest.mark.django_db
def test_transfer_ownership(owner_client, owner_a, manager_a):
    target = Membership.all_companies.get(user=manager_a)
    owner_client.post(
        "/app/team/", {"op": "transfer", "new_owner": target.pk, "my_new_role": Role.objects.get(key="manager").pk}
    )
    assert Membership.all_companies.get(user=manager_a).role.key == "owner"
    assert Membership.all_companies.get(user=owner_a).role.key == "manager"


@pytest.mark.django_db
def test_manager_cannot_manage_team_or_profile(client, manager_a):
    client.force_login(manager_a)
    assert client.get("/app/team/").status_code == 200
    assert client.post("/app/team/", {"op": "invite", "email": "z@a.example", "role": "x"}).status_code == 403
    assert client.patch("/api/v1/company/", {"name": "Hacked"}, content_type="application/json").status_code == 403
    assert (
        client.post("/api/v1/company/team/invitations/", {"email": "z@a.example", "role": "agent"}).status_code == 403
    )


@pytest.mark.django_db
def test_team_api(owner_client, manager_a, mailoutbox):
    created = owner_client.post("/api/v1/company/team/invitations/", {"email": "api@alpha.example", "role": "agent"})
    assert created.status_code == 201
    assert (
        owner_client.post(
            "/api/v1/company/team/invitations/", {"email": "bad@alpha.example", "role": "owner"}
        ).status_code
        == 400
    )
    inv_id = created.json()["id"]
    assert owner_client.post(f"/api/v1/company/team/invitations/{inv_id}/resend/").status_code == 200
    assert owner_client.delete(f"/api/v1/company/team/invitations/{inv_id}/").status_code == 204
    members = owner_client.get("/api/v1/company/team/members/").json()
    m_id = next(m["id"] for m in members if m["email"] == "manager@alpha.example")
    assert owner_client.post(f"/api/v1/company/team/members/{m_id}/role/", {"role": "agent"}).json()["role"] == "agent"
    assert owner_client.post(f"/api/v1/company/team/members/{m_id}/deactivate/").json()["status"] == "disabled"

    token = invite_link(mailoutbox).split("/")[2]
    info = Client().get(f"/public/v1/invitations/{token}/")
    assert info.status_code == 400  # cancelled above


@pytest.mark.django_db
def test_public_invitation_api_creates_account(owner_client, mailoutbox):
    owner_client.post("/api/v1/company/team/invitations/", {"email": "app@alpha.example", "role": "agent"})
    token = invite_link(mailoutbox).split("/")[2]
    anon = Client()
    assert anon.get(f"/public/v1/invitations/{token}/").json()["has_account"] is False
    assert anon.post(f"/public/v1/invitations/{token}/", {"full_name": "A", "password": "short"}).status_code == 400
    ok = anon.post(f"/public/v1/invitations/{token}/", {"full_name": "App User", "password": PASSWORD})
    assert ok.status_code == 201 and Membership.all_companies.filter(user__email="app@alpha.example").exists()


@pytest.mark.django_db
def test_cross_company_ids_are_not_reachable(client, owner_b, manager_a):
    client.force_login(owner_b)
    target = Membership.all_companies.get(user=manager_a)
    assert client.post(f"/api/v1/company/team/members/{target.pk}/deactivate/").status_code == 404
    client.post("/app/team/", {"op": "deactivate", "member": target.pk})
    target.refresh_from_db()
    assert target.status == Membership.ACTIVE


@pytest.mark.django_db
def test_profile_hours_and_onboarding(owner_client, company_a):
    data = owner_client.get("/api/v1/company/onboarding/").json()
    assert data["total"] == 8 and not data["steps"][0]["done"]
    response = owner_client.patch(
        "/api/v1/company/",
        {
            "name": "Alpha Homes",
            "gstin": "27abcde1234f1z5",
            "address": "MG Road",
            "email": "hi@alpha.example",
            "phone": "9876543210",
            "status": "active",
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    company_a.refresh_from_db()
    assert company_a.name == "Alpha Homes" and company_a.gstin == "27ABCDE1234F1Z5" and company_a.status == "trial"
    bad = owner_client.put(
        "/api/v1/company/hours/",
        {"business_hours": {"mon": {"open": "18:00", "close": "09:00"}}},
        content_type="application/json",
    )
    assert bad.status_code == 400
    hours = {
        d: {"open": "09:00", "close": "18:00", "closed": d == "sun"}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    ok = owner_client.put(
        "/api/v1/company/hours/",
        {"business_hours": hours, "holidays": [{"date": "2026-11-08", "name": "Diwali"}]},
        content_type="application/json",
    )
    assert ok.status_code == 200 and ok.json()["holidays"][0]["name"] == "Diwali"
    assert owner_client.get("/api/v1/company/onboarding/").json()["steps"][0]["done"]


@pytest.mark.django_db
def test_settings_page_saves_hours(owner_client, company_a):
    post = {"op": "hours", "holiday_date": ["2026-01-26"], "holiday_name": ["Republic Day"]}
    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        post.update({f"{d}_open": "10:00", f"{d}_close": "19:00"})
    owner_client.post("/app/settings/", post)
    company_a.refresh_from_db()
    assert company_a.business_hours["mon"] == {"open": "10:00", "close": "19:00", "closed": False}
    assert company_a.holidays == [{"date": "2026-01-26", "name": "Republic Day"}]


@pytest.mark.django_db
def test_panel_shell_menu_per_role_and_plan(owner_client, company_a, client):
    for url in ("/app/", "/app/settings/", "/app/team/", "/app/soon/leads/", "/profile/"):
        assert owner_client.get(url).status_code == 200, url
    html = owner_client.get("/app/").content.decode()
    for label in (
        "AI Employees",
        "Leads",
        "Calendar",
        "Conversations",
        "Campaigns",
        "Knowledge Base",
        "Catalogue",
        "Analytics",
        "Billing &amp; Usage",
        "Team",
        "Settings",
        "Support",
    ):
        assert label in html, label
    from apps.billing.models import Plan

    plan = Plan.objects.get(key="starter")
    PlanEntitlement.objects.create(plan=plan, key="campaigns", limit_value=0)
    company_a.plan = plan
    company_a.save()
    assert "Campaigns" not in owner_client.get("/app/").content.decode()
    assert owner_client.get("/app/soon/unknown/").status_code == 404


@pytest.mark.django_db
def test_company_panel_uses_its_own_accent_colour(owner_client, set_setting):
    set_setting("general.color_company_panel", "#123456")
    assert b"--brand-primary:#123456" in owner_client.get("/app/").content
