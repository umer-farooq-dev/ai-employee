# ruff: noqa: F811 — pytest fixtures imported from the voice tests
"""Phase 7 part 4: support tickets (SA-19, CP-05), data export and account deletion (TEN-07, COMP-09), retention
(SEC-12) and the e-mail / SMS providers in Super Admin (SA-10)."""

import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import Invoice
from apps.crm import services as crm
from apps.crm.models import Lead
from apps.notifications import sms
from apps.notifications.models import Notification
from apps.providers.models import Provider
from apps.support import services as support
from apps.support.models import Ticket
from apps.tenancy import privacy
from apps.tenancy.context import company_context
from apps.tenancy.models import Company, DataRequest

from .conftest import make_user
from .test_voice_calls import WINDOW, realty, sara  # noqa: F401 — fixtures


@pytest.fixture(autouse=True)
def _inline(monkeypatch):
    monkeypatch.setattr(privacy, "RUN_INLINE", True)


@pytest.mark.django_db
def test_ticket_round_trip(client, super_admin, company_a, owner_a, set_setting, django_capture_on_commit_callbacks):
    from django.test import Client

    admin_client = Client()
    admin_client.force_login(super_admin)
    set_setting("contact.team_notify_emails", ["team@platform.example"])
    client.force_login(owner_a)
    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(
            "/app/support/",
        {"subject": "Number not ringing", "category": "Calls and phone numbers", "priority": "high",
         "body": "Calls to our number do not reach the AI.", "file": SimpleUploadedFile("shot.png", b"\x89PNG data")},
    )  # fmt: skip
    with company_context(company_a.id):
        t = Ticket.objects.get(company=company_a)
    assert r["Location"] == f"/app/support/{t.pk}/" and t.number.startswith("T-") and t.priority == "high"
    with company_context(company_a.id):
        assert t.messages.get().attachment_name == "shot.png"
    assert any("Number not ringing" in m.subject and m.to == ["team@platform.example"] for m in mail.outbox)
    assert client.post("/app/support/", {"subject": "x", "body": "y", "category": "Nope"}).status_code == 200
    # Super Admin answers; an internal note stays hidden
    admin_client.post(
        f"/superadmin/support/{t.pk}/", {"op": "reply", "body": "Checking the routing.", "internal": "on"}
    )
    rr = admin_client.post(f"/superadmin/support/{t.pk}/", {"op": "reply", "body": "Fixed — please try again."})
    assert rr.status_code == 302, rr.content[:500]
    t.refresh_from_db()
    assert t.status == Ticket.ANSWERED and t.last_reply_by_staff
    page = client.get(f"/app/support/{t.pk}/").content.decode()
    assert "Fixed — please try again." in page and "Checking the routing." not in page
    with company_context(company_a.id):
        assert Notification.objects.filter(user=owner_a, kind="support").exists()
    assert any(m.to == [owner_a.email] and t.number in m.subject for m in mail.outbox)
    # the company replies → waiting for support; API sees the same ticket without the note
    client.post(f"/app/support/{t.pk}/", {"body": "Works now, thanks!"})
    t.refresh_from_db()
    assert t.status == Ticket.WAITING
    api = client.get(f"/api/v1/support/tickets/{t.pk}/").json()
    assert len(api["messages"]) == 3 and all(not m["body"].startswith("Checking") for m in api["messages"])
    created = client.post("/api/v1/support/tickets/", {"subject": "Invoice copy", "body": "Need the PDF"})
    assert created.status_code == 201 and created.json()["status"] == "open"
    # auto close after the configured days without a reply
    admin_client.post(f"/superadmin/support/{t.pk}/", {"op": "status", "status": "resolved"})
    set_setting("support.auto_close_days", 3)
    assert support.auto_close(now=timezone.now() + timedelta(days=4)) == 1
    t.refresh_from_db()
    assert t.status == Ticket.CLOSED
    assert client.post(f"/app/support/{t.pk}/", {"body": "again"}).status_code == 302
    with company_context(company_a.id):
        assert t.messages.count() == 4  # closed: the company cannot reply
    assert admin_client.get("/superadmin/support/?view=all").status_code == 200


@pytest.mark.django_db
def test_export_zip_and_download(client, realty, owner_a, sara):
    with company_context(realty.id):
        crm.create_lead(realty, {"name": "Ravi", "phone": "+919800000001"})
    client.force_login(owner_a)
    client.post("/app/settings/privacy/", {"op": "export"})
    with company_context(realty.id):
        req = DataRequest.objects.get(company=realty, kind="export")
    assert req.status == DataRequest.READY and req.expires_at
    assert any("export is ready" in m.subject for m in mail.outbox)
    r = client.get(f"/app/settings/privacy/{req.pk}/download/")
    z = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
    leads = json.loads(z.read("data/crm.lead.json"))
    assert (
        leads[0]["name"] == "Ravi" and "company.json" in z.namelist() and "data/agents.aiemployee.json" in z.namelist()
    )
    assert json.loads(z.read("data/team.json"))[0]["user__email"] == owner_a.email
    # expired links stop working and the file is removed
    privacy.run(now=req.expires_at + timedelta(minutes=1))
    req.refresh_from_db()
    assert (
        req.status == DataRequest.EXPIRED and client.get(f"/app/settings/privacy/{req.pk}/download/").status_code == 404
    )


@pytest.mark.django_db
def test_deletion_grace_cancel_and_purge(client, realty, owner_a, sara, set_setting):
    from apps.voice.models import PhoneNumber

    set_setting("privacy.deletion_grace_days", 30)
    agent = make_user("agent@alpha.example")
    from apps.rbac.models import Role
    from apps.tenancy.services import add_member

    add_member(realty, agent.email, Role.objects.get(scope="company", key="agent"))
    tw = Provider.objects.get(key="twilio")
    number = PhoneNumber.objects.create(provider=tw, e164="+918045678901", company=realty)
    with company_context(realty.id):
        crm.create_lead(realty, {"name": "Ravi", "phone": "+919800000001"})
        inv = billing.issue_invoice(realty, "Starter", 299900, paid=True)
    client.force_login(owner_a)
    client.post("/app/settings/privacy/", {"op": "delete", "confirm": "wrong name"})
    with company_context(realty.id):
        assert not DataRequest.objects.filter(kind="deletion").exists()
    client.post("/app/settings/privacy/", {"op": "delete", "confirm": realty.name, "reason": "Closing"})
    with company_context(realty.id):
        req = DataRequest.objects.get(kind="deletion")
    assert req.status == DataRequest.SCHEDULED and (req.scheduled_for - timezone.now()).days >= 29
    client.post("/app/settings/privacy/", {"op": "cancel", "request": str(req.pk)})
    req.refresh_from_db()
    assert req.status == DataRequest.CANCELLED
    client.post("/app/settings/privacy/", {"op": "delete", "confirm": realty.name})
    with company_context(realty.id):
        req = DataRequest.objects.get(kind="deletion", status="scheduled")
    assert privacy.run(now=timezone.now() + timedelta(days=1))["deleted"] == 0  # still in the grace period
    out = privacy.run(now=req.scheduled_for + timedelta(minutes=1))
    assert out["deleted"] == 1
    company = Company.objects.get(pk=realty.pk)
    assert company.deleted_at and company.name.startswith("Deleted company") and company.email == ""
    with company_context(realty.id):
        assert not Lead.all_companies.filter(company=realty).exists()
        assert Invoice.objects.filter(pk=inv.pk).exists()  # tax record kept
    number.refresh_from_db()
    assert number.company_id is None  # back in the pool
    from django.contrib.auth import get_user_model

    assert not get_user_model().objects.filter(email__in=[owner_a.email, agent.email]).exists()


@pytest.mark.django_db
def test_only_owner_deletes_and_retention(client, realty, owner_a, set_setting):
    from apps.audit.models import ApiRequestLog
    from apps.rbac.models import Role
    from apps.tenancy.services import add_member

    manager = make_user("manager@alpha.example")
    add_member(realty, manager.email, Role.objects.get(scope="company", key="manager"))
    client.force_login(manager)
    assert client.get("/app/settings/privacy/").status_code == 403  # company.manage needed
    old = ApiRequestLog.objects.create(path="/api/v1/x", method="GET", status=200, duration_ms=1)
    ApiRequestLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
    set_setting("retention.logs_days", 180)
    out = privacy.retention()
    assert out["api_logs"] == 1 and not ApiRequestLog.objects.filter(pk=old.pk).exists()


@pytest.mark.django_db
def test_email_and_sms_providers(monkeypatch, settings):
    from django.core.mail import EmailMessage

    from apps.notifications import backends

    sent = []

    class FakeSMTP:
        def __init__(self, **kw):
            sent.append(("conn", kw))

        def send_messages(self, msgs):
            sent.extend(("msg", m.from_email) for m in msgs)
            return len(msgs)

    monkeypatch.setattr(backends, "get_connection", lambda backend=None, **kw: FakeSMTP(backend=backend, **kw))
    backend = backends.ProviderEmailBackend()
    settings.EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    backend.send_messages([EmailMessage("Hi", "x", "AI Employee <no-reply@localhost>", ["a@b.example"])])
    assert sent[0][1]["backend"] == "django.core.mail.backends.locmem.EmailBackend"  # no provider: fallback
    smtp = Provider.objects.get(key="smtp")
    smtp.api_key, smtp.is_active = "smtp-pass", True
    smtp.config = {"host": "smtp.example.com", "port": "465", "username": "u", "security": "ssl",
                   "from_address": "hello@client.example"}  # fmt: skip
    smtp.save()
    sent.clear()
    backend.send_messages([EmailMessage("Hi", "x", "AI Employee <no-reply@localhost>", ["a@b.example"])])
    conn = sent[0][1]
    assert (
        conn["host"] == "smtp.example.com"
        and conn["port"] == 465
        and conn["use_ssl"]
        and conn["password"] == "smtp-pass"
    )
    assert sent[1] == ("msg", "AI Employee <hello@client.example>")
    # SMS: MSG91 when switched on, else the development log
    logged, posted = [], []
    monkeypatch.setattr(sms, "_development_log", lambda to, text: logged.append(to))
    sms.send("+919800000001", "123456 is your code")
    assert logged == ["+919800000001"]
    m = Provider.objects.get(key="msg91")
    m.api_key, m.is_active, m.config = "authkey", True, {"sender": "AIEMPL", "dlt_template_id": "1107"}
    m.save()
    from apps.providers import adapters

    monkeypatch.setattr(adapters, "_request", lambda method, url, headers, body=None, timeout=60: posted.append(body))
    sms.send("+919800000001", "123456 is your code")
    assert posted[0]["DLT_TE_ID"] == "1107" and posted[0]["sms"][0]["to"] == ["919800000001"]
