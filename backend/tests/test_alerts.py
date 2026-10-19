# ruff: noqa: F811 — pytest fixtures imported from the CRM tests
"""Phase 6 part 5: team alerts (CP-03, NOTI-02, NOTI-03), hot-lead actions (SCORE-05), usage alerts, push devices and
Web Push / FCM (API-05, MOB-03), the installable app. Push services and Meta are faked; e-mails use the test outbox."""

import base64
import datetime as dt
import json
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client

from apps.agents.models import UsageEvent
from apps.billing.models import Plan, PlanEntitlement
from apps.billing.usage import send_usage_alerts
from apps.crm import services as crm
from apps.crm.models import AssignmentRule
from apps.notifications import alerts, push
from apps.notifications.models import Device, Notification
from apps.providers import services as providers
from apps.providers.adapters import ProviderError
from apps.providers.models import Provider
from apps.tenancy.context import company_context

from .test_crm import agent_a, new_lead, owner, realty  # noqa: F401 — fixtures


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def notes(user, **kw):
    return list(Notification.all_companies.filter(user=user, **kw).order_by("created_at"))


@pytest.fixture
def web_push(db):
    p = providers.save_provider(Provider.objects.get(key="web-push"), {})  # the VAPID pair is generated
    return providers.set_active(p, True)


class Browser:
    """A browser's push subscription (its own key pair), able to decrypt what the platform sends (RFC 8291)."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        pub = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.keys = {"p256dh": b64(pub), "auth": b64(self.auth)}
        self.pub = pub

    def decrypt(self, body):
        salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
        sender = body[21 : 21 + idlen]
        assert rs == 4096
        shared = self.key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender))
        ikm = HKDF(hashes.SHA256(), 32, self.auth, b"WebPush: info\x00" + self.pub + sender).derive(shared)
        cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
        nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
        plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
        assert plain.endswith(b"\x02")
        return json.loads(plain[:-1])


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    def fake(method, url, headers, data=None, timeout=60, as_json=True):
        if "gone" in url:
            raise ProviderError("HTTP 410: subscription expired")
        sent.append((url, headers, data))
        return b"", {}

    monkeypatch.setattr(push, "request_raw", fake)
    return sent


# ---------------------------------------------------------------- notify: bell + chosen channels
@pytest.mark.django_db
def test_alert_goes_to_bell_and_the_channels_each_person_chose(realty, owner_a, set_setting):
    with company_context(realty.id):
        alerts.notify(realty, [owner_a, owner_a], "hot_lead", "Hot lead: Asha", "Budget given", "/app/leads/")
    rows = notes(owner_a)
    assert len(rows) == 1 and rows[0].read_at is None  # one per person
    assert rows[0].delivery["email"] == "skipped: No e-mail for this alert."  # caller gave no e-mail
    assert rows[0].delivery["push"].startswith("skipped: No device")
    # the person switches e-mail on only; the platform default no longer applies to this kind
    with company_context(realty.id):
        assert alerts.save_prefs(owner_a, {"hot_lead": ["email"]})["hot_lead"] == {
            "email": True,
            "whatsapp": False,
            "push": False,
        }
        ctx = {"lead_name": "Ravi", "lead_reference": "LD-1", "lead_phone": "", "score": 80, "reason": ""}
        alerts.notify(realty, [owner_a], "hot_lead", "Hot lead: Ravi", "", "/app/", email=("alerts/hot_lead", ctx))
    assert list(notes(owner_a)[-1].delivery) == ["email"] and mail.outbox[-1].to == [owner_a.email]
    assert "Hot lead" in mail.outbox[-1].subject and "/app/" in mail.outbox[-1].body
    with pytest.raises(ValidationError):
        alerts.save_prefs(owner_a, {"hot_lead": ["sms"]})
    with pytest.raises(ValidationError):
        alerts.save_prefs(owner_a, {"nope": ["email"]})
    # WhatsApp needs the company's approved team-alert template and the person's mobile number
    alerts.save_prefs(owner_a, {"usage": ["whatsapp"]})
    with company_context(realty.id):
        alerts.notify(realty, [owner_a], "usage", "80% used", "", "/app/")
    assert notes(owner_a)[-1].delivery["whatsapp"].startswith("skipped: No mobile number")
    owner_a.phone = "+919800000099"
    owner_a.save()
    with company_context(realty.id):
        alerts.notify(realty, [owner_a], "usage", "80% used", "", "/app/")
    assert "Alert to your team" in notes(owner_a)[-1].delivery["whatsapp"]
    set_setting("notifications.whatsapp_enabled", False)
    with company_context(realty.id):
        alerts.notify(realty, [owner_a], "usage", "80% used", "", "/app/")
    assert "switched off for the platform" in notes(owner_a)[-1].delivery["whatsapp"]
    set_setting("notifications.default_channels", ["email"])
    from apps.platform_config import services as config

    with pytest.raises(ValidationError):
        config.clean("notifications.default_channels", "email\nfax")


# ---------------------------------------------------------------- Web Push and FCM (MOB-03, API-05)
@pytest.mark.django_db
def test_web_push_is_encrypted_for_the_browser_and_signed(realty, owner_a, web_push, pushes):
    import jwt

    assert web_push.api_key.startswith("-----BEGIN PRIVATE KEY") and push.public_key()
    browser = Browser()
    push.register(owner_a, "web", "https://fcm.googleapis.com/fcm/send/abc", browser.keys, "Chrome")
    push.register(owner_a, "web", "https://push.example/gone", browser.keys, "Old")
    with company_context(realty.id):
        note = alerts.notify(realty, [owner_a], "handoff", "Ravi wants a person", "Sara · keyword", "/app/inbox/")[0]
    note.refresh_from_db()
    assert note.delivery["push"] == "sent"
    url, headers, body = pushes[0]
    assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == "3600"
    token = headers["Authorization"].split("t=")[1].split(",")[0]
    public = serialization.load_pem_private_key(web_push.api_key.encode(), None).public_key()
    claims = jwt.decode(token, public, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"].startswith("mailto:") and f"k={push.public_key()}" in headers["Authorization"]
    message = browser.decrypt(body)
    assert message == {"title": "Ravi wants a person", "body": "Sara · keyword", "url": "/app/inbox/",
                       "kind": "handoff", "id": str(note.pk)}  # fmt: skip
    assert not Device.objects.filter(name="Old").exists()  # the expired subscription was removed
    with pytest.raises(ProviderError):
        push.register(owner_a, "web", "http://insecure", browser.keys)
    with pytest.raises(ProviderError):
        push.register(owner_a, "web", "https://x", {})


@pytest.mark.django_db
def test_fcm_for_the_mobile_app(realty, owner_a, monkeypatch):
    from apps.providers import vendors

    p = Provider.objects.get(key="firebase")
    providers.set_active(providers.save_provider(p, {"api_key": json.dumps({"project_id": "aie-app"})}), True)
    calls = []
    monkeypatch.setattr(vendors, "_google_token", lambda provider, timeout: "ya29.token")
    monkeypatch.setattr(push, "_request", lambda method, url, headers, body, timeout: calls.append((url, body)))
    push.register(owner_a, "android", "fcm-token-1", name="Pixel")
    assert push.send(owner_a, {"title": "Hot lead", "body": "Asha", "url": "/app/", "kind": "hot_lead", "id": "1"}) == 1
    url, body = calls[0]
    assert url == "https://fcm.googleapis.com/v1/projects/aie-app/messages:send"
    assert body["message"]["token"] == "fcm-token-1" and body["message"]["notification"]["title"] == "Hot lead"
    assert vendors.test(Provider.objects.get(key="firebase")) == "Connected · Firebase project aie-app"


# ---------------------------------------------------------------- SCORE-05 hot-lead actions
@pytest.mark.django_db
def test_hot_lead_is_assigned_and_the_salesperson_alerted(realty, owner_a, agent_a):
    lead = new_lead(realty, phone="+919811111191", custom={"budget": "1 cr", "timeline": "Within 30 days"})
    assert lead.assigned_user is None
    AssignmentRule.all_companies.create(
        company=realty, name="To agent", priority=0, strategy="user", targets=[str(agent_a.pk)]
    )
    with company_context(realty.id):
        crm.apply_event(lead, "appointment_booked")  # → hot
        lead.refresh_from_db()
    assert lead.score_label == "hot" and lead.assigned_user == agent_a
    alert = notes(agent_a, kind="hot_lead")[0]
    assert alert.title.startswith("Hot lead: Test") and alert.url == f"/app/leads/{lead.pk}/"
    assert notes(owner_a, kind="hot_lead") == []  # the assigned person only
    assert any(m.to == [agent_a.email] and "Hot lead" in m.subject for m in mail.outbox)
    # staying hot does not alert again; the company can switch both actions off
    with company_context(realty.id):
        crm.rescore(lead)
        rules = crm.save_hot_policy(realty, {"notify": False, "assign": False})
    assert rules == {"notify": False, "assign": False} and len(notes(agent_a, kind="hot_lead")) == 1
    other = new_lead(realty, phone="+919811111192", custom={"budget": "1 cr", "timeline": "Within 30 days"})
    AssignmentRule.all_companies.all().delete()
    with company_context(realty.id):
        other.assigned_user = None
        other.save()
        crm.apply_event(other, "appointment_booked")
        other.refresh_from_db()
    assert other.score_label == "hot" and other.assigned_user is None and len(notes(agent_a, kind="hot_lead")) == 1


@pytest.mark.django_db
def test_unassigned_hot_lead_alerts_everyone_who_assigns(realty, owner_a, agent_a):
    lead = new_lead(realty, phone="+919811111193", custom={"budget": "1 cr", "timeline": "Within 30 days"})
    with company_context(realty.id):
        crm.save_hot_policy(realty, {"assign": False})
        crm.apply_event(lead, "appointment_booked")
    assert len(notes(owner_a, kind="hot_lead")) == 1  # owner may assign leads
    assert notes(agent_a, kind="hot_lead") == []  # a human agent may not


# ---------------------------------------------------------------- usage alerts
@pytest.mark.django_db
def test_usage_alerts_once_per_level_and_month(realty, owner_a, agent_a):
    realty.plan = Plan.objects.order_by("sort_order").first()
    realty.save(update_fields=["plan"])
    PlanEntitlement.objects.update_or_create(plan=realty.plan, key="ai_credits", defaults={"limit_value": 100})
    UsageEvent.all_companies.create(company=realty, meter="ai_credits", quantity=85, unit="credits")
    assert send_usage_alerts() == 1
    alert = notes(owner_a, kind="usage")[0]
    assert alert.title == "85% of your ai credits used this month" and alert.data["level"] == 80
    assert notes(agent_a, kind="usage") == []  # only people who see billing
    assert send_usage_alerts() == 0
    UsageEvent.all_companies.create(company=realty, meter="ai_credits", quantity=20, unit="credits")
    assert send_usage_alerts() == 1 and notes(owner_a, kind="usage")[-1].data["level"] == 100
    assert "105 of 100" in mail.outbox[-1].body


# ---------------------------------------------------------------- the bell, the centre and the API (NOTI-02)
@pytest.mark.django_db
def test_bell_api_centre_and_isolation(owner, realty, owner_a, agent_a, company_b, owner_b):
    with company_context(realty.id):
        mine = alerts.notify(realty, [owner_a], "appointment", "New booking", "Asha", "/app/calendar/")[0]
        alerts.notify(realty, [owner_a], "campaign", "Campaign finished", "", "https://evil.example/")
        alerts.notify(realty, [agent_a], "hot_lead", "Not yours", "", "/app/")
    assert owner.get("/api/v1/notifications/unread-count/").json() == {"unread": 2}
    rows = owner.get("/api/v1/notifications/").json()["results"]
    assert [r["title"] for r in rows] == ["Campaign finished", "New booking"]
    assert owner.get("/api/v1/notifications/?unread=1").json()["results"][0]["kind_label"] == "Campaigns"
    assert owner.post(f"/api/v1/notifications/{mine.pk}/read/").json() == {"updated": 1}
    page = owner.get("/app/notifications/").content.decode()
    assert "Campaign finished" in page and "Not yours" not in page
    assert owner.get(f"/app/notifications/{mine.pk}/open/").url == "/app/calendar/"
    evil = notes(owner_a, kind="campaign")[0]
    assert owner.get(f"/app/notifications/{evil.pk}/open/").url == "/app/notifications/"  # panel links only
    assert owner.post("/api/v1/notifications/read-all/").json() == {"updated": 0}
    other = notes(agent_a)[0]
    assert owner.get(f"/app/notifications/{other.pk}/open/").status_code == 404
    assert owner.post(f"/api/v1/notifications/{other.pk}/read/").json() == {"updated": 0}
    # settings
    assert owner.get("/api/v1/notifications/settings/").json()["handoff"] == {
        "email": True,
        "whatsapp": False,
        "push": True,
    }
    r = owner.patch("/api/v1/notifications/settings/", {"handoff": ["whatsapp"]}, content_type="application/json")
    assert r.json()["handoff"]["whatsapp"] is True
    assert owner.patch("/api/v1/notifications/settings/", {"x": []}, content_type="application/json").status_code == 400
    # devices (API-05)
    d = owner.post("/api/v1/devices/", {"platform": "ios", "token": "apns-fcm-1"}, content_type="application/json")
    assert d.status_code == 201 and owner.get("/api/v1/devices/").json()["results"][0]["platform"] == "ios"
    assert (
        owner.post("/api/v1/devices/", {"platform": "x", "token": "1"}, content_type="application/json").status_code
        == 400
    )
    assert owner.post("/api/v1/devices/remove/", {"token": "apns-fcm-1"}, content_type="application/json").json() == {
        "removed": 1
    }
    assert owner.get("/api/v1/push/config/").json() == {"web_push_public_key": "", "fcm": False}
    assert Client().get("/api/v1/notifications/").status_code in (401, 403)
    # the bell is in the topbar; the profile has the alert grid
    home = owner.get("/app/").content.decode()
    assert 'id="nb-count"' in home and "manifest.webmanifest" in home and "app-bottom-nav" in home
    owner.post("/profile/", {"op": "alerts", "hot_lead__push": "on", "usage__email": "on"})
    owner_a.refresh_from_db()
    assert owner_a.notification_prefs["alerts"]["hot_lead"] == ["push"]
    assert owner_a.notification_prefs["alerts"]["handoff"] == []
    assert "Push on your devices" in owner.get("/profile/").content.decode()


@pytest.mark.django_db
def test_installable_app_files(client, owner_a, set_setting):
    m = client.get("/manifest.webmanifest")
    data = json.loads(m.content)
    assert m["Content-Type"] == "application/manifest+json" and data["display"] == "standalone"
    assert data["start_url"] == "/app/" and {i["sizes"] for i in data["icons"]} >= {"192x192", "512x512"}
    set_setting("general.platform_name", "Client Brand")
    set_setting("general.app_icon", "/media/brand/icon.png")
    data = json.loads(client.get("/manifest.webmanifest").content)
    assert data["name"] == "Client Brand" and data["icons"][0]["src"] == "/media/brand/icon.png"
    sw = client.get("/sw.js")
    assert sw["Content-Type"].startswith("application/javascript") and sw["Service-Worker-Allowed"] == "/"
    assert b"showNotification" in sw.content and b"/media/brand/icon.png" in sw.content
    assert client.get("/offline/").status_code == 200


@pytest.mark.django_db
def test_test_push_from_profile(owner, owner_a, web_push, pushes):
    owner.post("/profile/", {"op": "test_push"})
    push.register(owner_a, "web", "https://fcm.googleapis.com/fcm/send/x", Browser().keys)
    r = owner.post("/profile/", {"op": "test_push"}, follow=True)
    assert "Test alert sent to 1 device" in r.content.decode() and len(pushes) == 1
    assert owner.post("/profile/", {"op": "remove_device", "device": str(Device.objects.get().pk)}).status_code == 302
    assert not Device.objects.exists()


@pytest.mark.django_db
def test_old_alerts_are_kept_with_dates(realty, owner_a):
    with company_context(realty.id):
        n = alerts.notify(realty, [owner_a], "usage", "x")[0]
    Notification.all_companies.filter(pk=n.pk).update(created_at=n.created_at - dt.timedelta(days=40))
    with company_context(realty.id):
        assert alerts.unread_count(owner_a, realty) == 1
