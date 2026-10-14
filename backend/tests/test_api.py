"""API-01 … API-07: REST API with OpenAPI docs, mobile JWT login, cursor pagination, error format, rate limits."""

import pytest

from .conftest import PASSWORD


@pytest.mark.django_db
def test_openapi_schema_lists_phase1_endpoints(admin_client):
    schema = admin_client.get("/api/v1/schema/", HTTP_ACCEPT="application/json").json()
    paths = set(schema["paths"])
    for path in (
        "/api/v1/me/",
        "/api/v1/company/",
        "/api/v1/admin/companies/",
        "/api/v1/admin/users/",
        "/api/v1/admin/roles/",
        "/api/v1/admin/plans/",
        "/api/v1/admin/cms/pages/",
        "/api/v1/admin/settings/{screen}/",
        "/api/v1/admin/logs/audit/",
        "/public/v1/branding/",
        "/public/v1/cms/{key}/",
        "/public/v1/plans/",
    ):
        assert path in paths, path


@pytest.mark.django_db
def test_mobile_jwt_login_reaches_the_api(client, owner_a, company_a):
    """API-02: the Flutter app logs in through the same endpoints and gets a Bearer token."""
    response = client.post(
        "/api/v1/auth/app/v1/auth/login",
        {"email": owner_a.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    token = response.json()["meta"]["access_token"]
    from django.test import Client

    app = Client()  # no session cookie: token only
    me = app.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me.status_code == 200 and me.json()["email"] == owner_a.email
    assert app.get("/api/v1/company/", HTTP_AUTHORIZATION=f"Bearer {token}").json()["id"] == str(company_a.id)
    assert app.get("/api/v1/admin/companies/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 403


@pytest.mark.django_db
def test_profile_update(client, owner_a):
    client.force_login(owner_a)
    response = client.patch(
        "/api/v1/me/", {"full_name": "Asha Rao", "availability": "online"}, content_type="application/json"
    )
    assert response.status_code == 200 and response.json()["full_name"] == "Asha Rao"
    page = client.post(
        "/profile/",
        {
            "full_name": "Asha R",
            "phone": "+919876543210",
            "timezone": "Asia/Kolkata",
            "availability": "away",
            "email_security_alerts": "on",
        },
    )
    assert page.status_code == 302
    owner_a.refresh_from_db()
    assert owner_a.availability == "away" and owner_a.notification_prefs["email_security_alerts"] is True


@pytest.mark.django_db
def test_admin_company_crud_and_cursor_pagination(admin_client):
    for i in range(3):
        created = admin_client.post(
            "/api/v1/admin/companies/",
            {"name": f"Company {i}", "plan": "starter", "owner_email": f"o{i}@example.com"},
            content_type="application/json",
        )
        assert created.status_code == 201, created.content
    page = admin_client.get("/api/v1/admin/companies/?page_size=2").json()
    assert len(page["results"]) == 2 and page["next"]
    company_id = page["results"][0]["id"]
    assert (
        admin_client.post(
            f"/api/v1/admin/companies/{company_id}/suspend/", {"reason": "x"}, content_type="application/json"
        ).json()["status"]
        == "suspended"
    )


@pytest.mark.django_db
def test_error_format_and_settings_api(admin_client):
    bad = admin_client.patch(
        "/api/v1/admin/settings/general/", {"contact.support_email": "nope"}, content_type="application/json"
    )
    body = bad.json()
    assert bad.status_code == 400 and set(body["error"]) == {"code", "message", "details", "request_id"}
    unknown = admin_client.patch(
        "/api/v1/admin/settings/general/", {"security.lockout_attempts": 3}, content_type="application/json"
    )
    assert unknown.status_code == 400  # system keys cannot be changed through the general screen
    ok = admin_client.patch(
        "/api/v1/admin/settings/general/", {"general.tagline": "24/7 AI workforce"}, content_type="application/json"
    )
    assert ok.json() == {"changed": ["general.tagline"]}


@pytest.mark.django_db
def test_rate_limit_from_settings(client, owner_a, set_setting):
    set_setting("security.api_rate_user", "2/minute")
    client.force_login(owner_a)
    codes = [client.get("/api/v1/me/").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


@pytest.mark.django_db
def test_public_endpoints_and_api_log(client):
    from apps.audit.models import ApiRequestLog

    plans = client.get("/public/v1/plans/").json()
    assert [p["key"] for p in plans] == ["starter", "business", "pro", "enterprise"]
    assert plans[0]["price_monthly_paise"] == 299900
    assert ApiRequestLog.objects.filter(path="/public/v1/plans/", status=200).exists()
