"""TEN-03 private signed files, upload validation from settings, field encryption, Indian number format."""

import time

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import crypto
from apps.core.storage import company_path, private_storage, signed_url
from apps.core.uploads import save_public, validate_upload
from apps.superadmin.templatetags.admin_tags import inr


@pytest.mark.django_db
def test_private_file_needs_valid_signed_url(client, company_a, set_setting, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    path = company_path(company_a.id, "kb", "brochure.pdf")
    assert path.startswith(f"tenants/{company_a.id}/kb/") and "brochure" not in path
    private_storage._wrapped = private_storage._wrapped.__class__(location=tmp_path)
    private_storage.save(path, SimpleUploadedFile("x.pdf", b"%PDF-1"))
    url = signed_url(path)
    assert client.get(url).status_code == 200
    assert client.get(url[:-3] + "xx/").status_code == 404  # tampered
    set_setting("security.signed_url_seconds", 1)
    time.sleep(2)
    assert client.get(url).status_code == 404  # expired


@pytest.mark.django_db
def test_upload_rules_come_from_settings(set_setting, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    with pytest.raises(ValidationError):
        validate_upload(SimpleUploadedFile("run.exe", b"x"))
    with pytest.raises(ValidationError):
        save_public(SimpleUploadedFile("doc.pdf", b"x"), "branding")  # images only
    set_setting("security.upload_max_mb", 1)
    with pytest.raises(ValidationError):
        validate_upload(SimpleUploadedFile("big.png", b"x" * (1024 * 1024 + 1)))
    assert save_public(SimpleUploadedFile("logo.png", b"\x89PNG"), "branding").startswith("/media/branding/")


def test_field_encryption_round_trip(settings):
    token = crypto.encrypt("provider-secret")
    assert token != "provider-secret" and crypto.decrypt(token) == "provider-secret"


@pytest.mark.django_db
def test_inr_format_follows_setting(set_setting):
    assert inr(299900) == "₹2,999" and inr(1234567800) == "₹1,23,45,678" and inr(None) == "—"
    set_setting("locale.number_format", "international")
    assert inr(1234567800) == "₹12,345,678"
