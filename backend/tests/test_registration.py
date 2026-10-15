"""Phase 2 gate E2E: visitor → register → verify → pending → Super Admin approves → login (AUTH-01, 02, 12)."""

import json

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.notifications import sms
from apps.tenancy.models import Company, Membership

from .conftest import PASSWORD, make_user

FORM = {
    "business_name": "Sunrise Realty",
    "full_name": "Asha Rao",
    "email": "asha@sunrise.example",
    "phone": "98765 43210",
    "industry": "real-estate",
    "city": "Pune",
    "state": "Maharashtra",
    "business_size": "11-50",
    "website": "https://sunrise.example",
    "gstin": "27abcde1234f1z5",
    "password1": PASSWORD,
    "password2": PASSWORD,
    "accept_terms": "on",
}


def register(client, **extra):
    return client.post("/accounts/signup/", {**FORM, **extra})


@pytest.fixture
def visitor(db):
    return Client()


@pytest.mark.django_db
def test_registration_creates_pending_company_and_notifies_team(client, set_setting, mailoutbox):
    set_setting("contact.team_notify_emails", ["ops@example.com"])
    response = register(client, plan="business")
    assert response.status_code == 302
    company = Company.objects.get(name="Sunrise Realty")
    owner = User.objects.get(email="asha@sunrise.example")
    assert company.status == Company.PENDING and company.plan.key == "business"
    assert company.gstin == "27ABCDE1234F1Z5" and company.industry.key == "real-estate"
    assert company.terms_accepted_at and company.terms_accepted_ip == "127.0.0.1"
    assert owner.phone == "+919876543210" and owner.full_name == "Asha Rao"
    membership = Membership.all_companies.get(company=company)
    assert membership.user == owner and membership.role.key == "owner"
    assert any(m.to == ["ops@example.com"] and "Sunrise Realty" in m.subject for m in mailoutbox)
    assert AuditLog.objects.filter(action="company.register").exists()


@pytest.mark.django_db
def test_terms_and_required_fields(client):
    response = register(client, accept_terms="", industry="", gstin="BAD")
    assert response.status_code == 200 and not Company.objects.exists()
    form = response.context["form"]
    assert {"accept_terms", "industry", "gstin"} <= set(form.errors)


@pytest.mark.django_db
def test_pending_company_sees_only_status_page(client):
    register(client)
    assert client.get("/app/").url == "/app/pending/"
    assert b"reviewing your details" in client.get("/app/pending/").content
    assert client.get("/api/v1/company/team/members/").json()["error"]["code"] == "company_pending"
    assert client.get("/api/v1/company/").json()["status"] == "pending"
    assert client.get("/").status_code == 200  # website stays open


@pytest.mark.django_db
def test_super_admin_approves_and_owner_gets_in(visitor, admin_client, mailoutbox, set_setting):
    set_setting("registration.trial_days", 7)
    register(visitor)
    company = Company.objects.get()
    response = admin_client.post(f"/superadmin/companies/{company.pk}/approval/", {"decision": "approve"})
    assert response.status_code == 302
    company.refresh_from_db()
    assert company.status == Company.TRIAL and company.approved_by.email == "admin@example.com"
    assert (company.trial_ends_at - company.approved_at).days in (6, 7)
    assert any(m.to == ["asha@sunrise.example"] and "approved" in m.subject for m in mailoutbox)
    assert visitor.get("/app/").status_code == 200


@pytest.mark.django_db
def test_reject_needs_reason_and_shows_it(visitor, admin_client):
    register(visitor)
    company = Company.objects.get()
    admin_client.post(f"/superadmin/companies/{company.pk}/approval/", {"decision": "reject", "reason": ""})
    company.refresh_from_db()
    assert company.status == Company.PENDING
    admin_client.post(f"/superadmin/companies/{company.pk}/approval/", {"decision": "reject", "reason": "Fake GST"})
    company.refresh_from_db()
    assert company.status == Company.REJECTED
    assert b"Fake GST" in visitor.get("/app/pending/").content


@pytest.mark.django_db
def test_approval_api_and_permissions(visitor, admin_client, support):
    register(visitor)
    company = Company.objects.get()
    other = Client()
    other.force_login(support)
    assert other.post(f"/api/v1/admin/companies/{company.pk}/approve/").status_code == 403
    pending = admin_client.get("/api/v1/admin/companies/?status=pending").json()["results"]
    assert [c["name"] for c in pending] == ["Sunrise Realty"]
    data = admin_client.post(f"/api/v1/admin/companies/{company.pk}/approve/").json()
    assert data["status"] == "trial"
    assert admin_client.post(f"/api/v1/admin/companies/{company.pk}/reject/", {"reason": "x"}).status_code == 400


@pytest.mark.django_db
def test_no_approval_and_no_trial_settings(client, set_setting):
    set_setting("registration.approval_required", False)
    set_setting("registration.trial_enabled", False)
    register(client)
    assert Company.objects.get().status == Company.ACTIVE
    assert client.get("/app/").status_code == 200


@pytest.mark.django_db
def test_mandatory_email_verification_from_settings(client, set_setting):
    set_setting("registration.email_verification", "mandatory")
    response = register(client)
    assert response.url == "/accounts/confirm-email/"
    assert not client.get("/app/").wsgi_request.user.is_authenticated


@pytest.mark.django_db
def test_mobile_otp_flow(client, set_setting, monkeypatch):
    sent = []
    monkeypatch.setitem(sms.PROVIDERS, "log", lambda to, text: sent.append((to, text)))
    set_setting("registration.mobile_otp_required", True)
    set_setting("registration.approval_required", False)
    register(client)
    assert client.get("/app/").url == "/app/pending/"
    client.post("/app/pending/", {"op": "send"})
    to, text = sent[-1]
    code = text.split()[0]
    assert to == "+919876543210" and len(code) == 6
    client.post("/app/pending/", {"op": "verify", "code": "000000" if code != "000000" else "111111"})
    assert client.get("/app/").url == "/app/pending/"
    client.post("/app/pending/", {"op": "verify", "code": code})
    assert client.get("/app/").status_code == 200
    assert User.objects.get(email=FORM["email"]).phone_verified_at


@pytest.mark.django_db
def test_otp_api_and_attempt_limit(client, set_setting, monkeypatch):
    sent = []
    monkeypatch.setitem(sms.PROVIDERS, "log", lambda to, text: sent.append(text))
    set_setting("registration.mobile_otp_required", True)
    set_setting("registration.otp_max_attempts", 2)
    register(client)
    assert client.post("/api/v1/me/phone-otp/", {"op": "send"}).json() == {"sent": True}
    for _ in range(2):
        assert client.post("/api/v1/me/phone-otp/", {"op": "verify", "code": "x"}).status_code == 400
    right = sent[-1].split()[0]
    assert client.post("/api/v1/me/phone-otp/", {"op": "verify", "code": right}).status_code == 400  # locked


@pytest.mark.django_db
def test_headless_api_signup_uses_the_same_form(client):
    payload = {**FORM, "password": PASSWORD, "accept_terms": True}
    for key in ("password1", "password2"):
        payload.pop(key)
    response = client.post("/api/v1/auth/app/v1/auth/signup", json.dumps(payload), content_type="application/json")
    assert response.status_code in (200, 401), response.content
    assert Company.objects.get().status == Company.PENDING


@pytest.mark.django_db
def test_registration_options_for_the_app(client):
    data = client.get("/public/v1/registration-options/").json()
    assert data["enabled"] and "Maharashtra" in data["states"]
    assert [i["key"] for i in data["industries"]] == ["real-estate", "travel", "education"]


@pytest.mark.django_db
def test_staff_user_never_gated(client, set_setting):
    set_setting("registration.mobile_otp_required", True)
    staff = make_user("ops@example.com", "super_admin")
    client.force_login(staff)
    assert client.get("/superadmin/").status_code == 200


@pytest.mark.django_db
def test_phone_field_country_from_settings(client, set_setting):
    html = client.get("/accounts/signup/").content.decode()
    assert "data-phone" in html and 'initialCountry: "in"' in html
    set_setting("locale.default_phone_country", "ae")
    assert 'initialCountry: "ae"' in client.get("/contact/").content.decode()
