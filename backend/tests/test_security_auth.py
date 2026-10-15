"""AUTH-03 … AUTH-06, SA-18, SEC-08: login, lockout, 2FA, sessions, IP allowlist, audit trail."""

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from apps.accounts.validators import SettingsMinimumLengthValidator
from apps.audit.models import AuditLog

from .conftest import PASSWORD, make_user


@pytest.mark.django_db
def test_login_success_and_failure_are_audited(client, owner_a):
    client.post("/accounts/login/", {"login": owner_a.email, "password": "wrong-password-1"})
    client.post("/accounts/login/", {"login": owner_a.email, "password": PASSWORD})
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"auth.login_failed", "auth.login"} <= actions


@pytest.mark.django_db
def test_lockout_uses_super_admin_setting(client, owner_a, set_setting):
    set_setting("security.lockout_attempts", 3)
    for _ in range(3):
        client.post("/accounts/login/", {"login": owner_a.email, "password": "wrong-password-1"})
    response = client.post("/accounts/login/", {"login": owner_a.email, "password": PASSWORD})
    assert response.status_code == 200 and not response.wsgi_request.user.is_authenticated
    assert AuditLog.objects.filter(action="auth.locked_out").exists()


@pytest.mark.django_db
def test_staff_must_set_up_2fa(client, set_setting):
    set_setting("security.staff_2fa_required", True)
    staff = make_user("new-staff@example.com", "super_admin", with_2fa=False)
    client.force_login(staff)
    response = client.get("/superadmin/")
    assert response.status_code == 302 and "/accounts/2fa/totp/activate" in response.url
    set_setting("security.staff_2fa_required", False)
    assert client.get("/superadmin/").status_code == 200


@pytest.mark.django_db
def test_company_2fa_enforcement(client, owner_a, company_a, set_setting):
    client.force_login(owner_a)
    assert client.get("/app/").status_code == 200
    company_a.require_2fa = True
    company_a.save()
    assert "/accounts/2fa/" in client.get("/app/").url


@pytest.mark.django_db
def test_inactivity_timeout_from_settings(client, owner_a, set_setting):
    import time

    set_setting("security.session_timeout_minutes", 30)
    client.force_login(owner_a)
    assert client.get("/app/").status_code == 200
    session = client.session
    session["last_activity"] = int(time.time()) - 31 * 60  # idle for 31 minutes
    session.save()
    response = client.get("/app/")
    assert response.status_code == 302 and "/accounts/login/" in response.url
    assert client.get("/app/").status_code == 302  # signed out


@pytest.mark.django_db
def test_admin_ip_allowlist(admin_client, set_setting):
    set_setting("security.admin_ip_allowlist", ["10.0.0.0/8"])
    assert admin_client.get("/superadmin/").status_code == 403
    set_setting("security.admin_ip_allowlist", ["127.0.0.1"])
    assert admin_client.get("/superadmin/").status_code == 200


@pytest.mark.django_db
def test_password_policy_from_settings(set_setting):
    set_setting("security.password_min_length", 14)
    with pytest.raises(ValidationError):
        SettingsMinimumLengthValidator().validate("short-pass-1")
    SettingsMinimumLengthValidator().validate("a-long-enough-pass")


@pytest.mark.django_db
def test_registration_switch_closes_signup(client, set_setting):
    set_setting("registration.enabled", False)
    assert b"closed" in client.get("/accounts/signup/").content.lower()
    assert b"/accounts/signup/" not in client.get("/accounts/login/").content
    set_setting("registration.enabled", True)
    assert b"/accounts/signup/" in client.get("/accounts/login/").content


@pytest.mark.django_db
def test_audit_log_is_append_only(owner_a):
    entry = AuditLog.objects.create(action="test", actor_email=owner_a.email)
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).update(action="tampered")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).delete()


@pytest.mark.django_db
def test_2fa_secret_encrypted_at_rest():
    from apps.accounts.adapter import MFAAdapter

    adapter = MFAAdapter()
    token = adapter.encrypt("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP" and adapter.decrypt(token) == "JBSWY3DPEHPK3PXP"


@pytest.mark.django_db
def test_super_admin_on_its_own_host(client, settings, super_admin):
    """Staff and website / company sessions never share a cookie: Super Admin is served only on ADMIN_HOST."""
    settings.ADMIN_HOST = "admin.testserver"
    settings.ALLOWED_HOSTS = ["testserver", "admin.testserver"]
    response = client.get("/superadmin/companies/?q=x")
    assert response.url == "http://admin.testserver/superadmin/companies/?q=x"
    assert client.get("/superadmin/", HTTP_HOST="admin.testserver").status_code == 302  # login on the admin host
    client.force_login(super_admin)  # staff signed in on the website host …
    landing = client.get("/dashboard/")
    assert landing.url.startswith("http://admin.testserver/accounts/login/")
    assert not client.get("/accounts/signup/").wsgi_request.user.is_authenticated  # … is signed out there
    assert client.get("/accounts/signup/").status_code == 200
    assert b"/accounts/signup/" not in client.get("/accounts/login/", HTTP_HOST="admin.testserver").content
