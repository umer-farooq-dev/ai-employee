"""SA-16, SA-21 … SA-27: settings live in the database, are validated, audited and shown everywhere."""

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.platform_config import services as config
from apps.platform_config.registry import SETTINGS


@pytest.mark.django_db
def test_every_registry_key_is_seeded_in_the_database():
    from apps.platform_config.models import PlatformSetting

    assert set(PlatformSetting.objects.values_list("key", flat=True)) >= {s.key for s in SETTINGS}


@pytest.mark.django_db
def test_update_validates_saves_and_audits(super_admin):
    changed = config.update({"general.platform_name": "Sara AI", "security.lockout_attempts": 7}, user=super_admin)
    assert set(changed) == {"general.platform_name", "security.lockout_attempts"}
    assert config.get("general.platform_name") == "Sara AI"
    assert AuditLog.objects.filter(action="settings.update").exists()
    for bad in (
        {"contact.support_email": "not-an-email"},
        {"security.lockout_attempts": 1},
        {"security.admin_ip_allowlist": "999.1.1.1"},
        {"general.color_primary": "purple"},
        {"locale.timezone": "Mars/Base"},
        {"security.api_rate_user": "fast"},
    ):
        with pytest.raises(ValidationError):
            config.update(bad)
    with pytest.raises(KeyError):
        config.get("not.a.setting")


@pytest.mark.django_db
def test_branding_shown_everywhere(set_setting, super_admin):
    from django.test import Client

    client, admin_client = Client(), Client()
    admin_client.force_login(super_admin)
    set_setting("general.platform_name", "Sara AI")
    set_setting("contact.copyright", "© {year} Sara AI Pvt Ltd")
    assert b"Sara AI" in client.get("/").content  # website title / header
    assert b"Sara AI" in client.get("/accounts/login/").content  # login page
    page = admin_client.get("/superadmin/").content.decode()
    assert "Sara AI" in page and "Pvt Ltd" in page  # panel title and footer
    assert admin_client.get("/public/v1/branding/").json()["general.platform_name"] == "Sara AI"


@pytest.mark.django_db
def test_maintenance_mode(client, set_setting, admin_client):
    set_setting("maintenance.enabled", True)
    set_setting("maintenance.message", "Back at 6 pm")
    from django.test import Client

    anon = Client()
    response = anon.get("/")
    assert response.status_code == 503 and b"Back at 6 pm" in response.content
    assert anon.get("/public/v1/branding/").status_code == 503
    assert admin_client.get("/superadmin/").status_code == 200  # Super Admin keeps working


@pytest.mark.django_db
def test_general_settings_screen_saves(admin_client):
    response = admin_client.post(
        "/superadmin/settings/general/?tab=branding",
        {
            "general.platform_name": "Sara AI",
            "general.short_name": "SA",
            "general.tagline": "24/7",
            "general.color_primary": "#112233",
            "general.color_secondary": "#445566",
            "general.widget_powered_by": "x",
        },
    )
    assert response.status_code == 302
    assert config.get("general.color_primary") == "#112233"
