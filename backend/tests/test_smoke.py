import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User


@pytest.mark.django_db
def test_user_logs_in_with_email_and_uuid_key():
    user = User.objects.create_user("Owner@Example.com", "a-strong-password-123")
    assert user.email == "owner@example.com"
    assert user.check_password("a-strong-password-123")
    assert len(str(user.pk)) == 36  # UUID primary key


def test_phone_must_be_international_format():
    User(email="x@example.com", phone="+919876543210").clean_fields(exclude=["password"])
    with pytest.raises(ValidationError):
        User(email="x@example.com", phone="(987) 654-3210").clean_fields(exclude=["password"])


def test_django_admin_is_not_installed(settings):
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


@pytest.mark.django_db
def test_website_home_and_healthz(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz/").json() == {"status": "ok"}


@pytest.mark.django_db
def test_landing_after_login(client, super_admin, owner_a):
    client.force_login(owner_a)
    assert client.get("/dashboard/").url == "/app/"
    assert client.get("/superadmin/").status_code == 403  # company users never reach Super Admin
    client.force_login(super_admin)
    assert client.get("/dashboard/").url == "/superadmin/"
    assert client.get("/superadmin/").status_code == 200


@pytest.mark.django_db
def test_company_panel_requires_login(client):
    assert client.get("/app/").status_code == 302
