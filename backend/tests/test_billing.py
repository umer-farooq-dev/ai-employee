# ruff: noqa: F811 — pytest fixtures imported from the voice tests
"""Phase 7 part 2: subscriptions, GST invoices, payments, holds, limits, credits and feature flags (SUB-03 … SUB-06,
USE-02 … USE-04, SA-20). Razorpay is faked (no network); signatures are real HMACs."""

import hashlib
import hmac
import io
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from pypdf import PdfReader

from apps.agents import runtime
from apps.billing import access, gst, limits, razorpay, usage
from apps.billing import services as billing
from apps.billing.models import CreditAdjustment, Invoice, Payment, Plan, PlanEntitlement, Subscription
from apps.providers.models import Provider
from apps.rbac.services import has_perm
from apps.tenancy.context import company_context
from apps.tenancy.models import Company

from .test_voice_calls import WINDOW, realty, sara  # noqa: F401 — fixtures

SECRET, HOOK = "rzp_key_secret", "rzp_webhook_secret"


class FakeRazorpay:
    def __init__(self, monkeypatch):
        self.calls, self.n = [], 0
        monkeypatch.setattr(razorpay, "_call", self.call)

    def call(self, p, method, path, body=None):
        self.calls.append((method, path, body))
        self.n += 1
        kind = {"/v1/plans": "plan", "/v1/subscriptions": "sub", "/v1/orders": "order"}.get(path, "obj")
        return {"id": f"{kind}_{self.n}"}

    def paths(self, method):
        return [p for m, p, _ in self.calls if m == method]


def sign(message, secret=SECRET):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def rzp(db, monkeypatch, set_setting):
    p = Provider.objects.get(key="razorpay")
    p.api_key, p.config, p.webhook_secret, p.is_active = SECRET, {"key_id": "rzp_test_abc"}, HOOK, True
    p.save()
    set_setting("billing.seller_state", "27")
    return FakeRazorpay(monkeypatch)


@pytest.fixture
def co(company_a, owner_a):
    company_a.plan = Plan.objects.get(key="starter")
    company_a.status, company_a.trial_ends_at = Company.TRIAL, timezone.now() + timedelta(days=10)
    company_a.gstin, company_a.state, company_a.email = "27ABCDE1234F1Z5", "Maharashtra", "billing@alpha.example"
    company_a.save()
    return company_a


def fresh(company):
    return Company.objects.get(pk=company.pk)


def sub_of(company):
    with company_context(company.id):
        return Subscription.objects.get(company=company)


def subscribe(client, co, plan="starter", interval="monthly"):
    r = client.post(
        "/app/billing/checkout/",
        {"plan": str(Plan.objects.get(key=plan).pk), "interval": interval},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    sid = r.json()["subscription_id"]
    pay = "pay_first"
    return (
        client.post(
            "/app/billing/confirm/",
            {"razorpay_payment_id": pay, "razorpay_subscription_id": sid, "razorpay_signature": sign(f"{pay}|{sid}")},
            content_type="application/json",
        ),
        sid,
    )


def hook(client, event, **payload):
    body = json.dumps({"event": event, "payload": payload})
    return client.post(
        "/webhooks/razorpay/", body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK)
    )


# ------------------------------------------------------------------ GST (SUB-06)
@pytest.mark.django_db
def test_gst_split_numbers_and_pdf(co, set_setting):
    set_setting("billing.seller_state", "27")
    set_setting("billing.sac_code", "998314")
    assert gst.split(300000, 18, "27", "27") == {
        "intra_state": True,
        "cgst": 27000,
        "sgst": 27000,
        "igst": 0,
        "total": 354000,
    }
    assert gst.split(300000, 18, "27", "29")["igst"] == 54000
    assert gst.split(100, 18, "27", "")["intra_state"]  # buyer state unknown → seller's state
    assert gst.state_code("29AAAAA0000A1Z5", "Maharashtra") == "29" and gst.state_code("", "kerala") == "32"
    with pytest.raises(ValidationError):
        gst.clean_gstin("27ABC")
    assert gst.taxable_from_inclusive(354000, 18) == 300000
    with company_context(co.id):
        a = billing.issue_invoice(co, "Starter plan", 299900, plan=co.plan, paid=True)
        b = billing.issue_invoice(co, "Extra", 10000)
        assert a.intra_state and a.cgst_paise == a.sgst_paise == 26991 and a.total_paise == 353882
        assert a.number.startswith("INV/") and int(b.number[-5:]) == int(a.number[-5:]) + 1 and len(a.number) <= 16
        co.gstin, co.state = "29ABCDE1234F1Z5", ""
        c = billing.issue_invoice(co, "Other state", 100000)
        assert not c.intra_state and c.igst_paise == 18000 and c.place_of_supply == "Karnataka (29)"
        pdf = billing.invoice_pdf(a)
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "TAX INVOICE" in text and a.number in text and "998314" in text and "CGST @ 9%" in text
    assert "Rupees Three Thousand Five Hundred Thirty Eight and Eighty Two Paise Only" in text


# ------------------------------------------------------------------ subscribe, renew, fail, hold (SUB-03)
@pytest.mark.django_db
def test_subscribe_renew_fail_hold_and_recover(client, co, owner_a, rzp, set_setting):
    client.force_login(owner_a)
    r, sid = subscribe(client, co)
    assert r.status_code == 200, r.content
    co = fresh(co)
    assert co.status == Company.ACTIVE and co.trial_ends_at is None and not co.billing_hold
    sub = sub_of(co)
    assert sub.status == Subscription.ACTIVE and sub.gateway_subscription_id == sid and sub.current_period_end
    with company_context(co.id):
        inv = Invoice.objects.get(company=co)
        assert inv.status == Invoice.PAID and inv.total_paise == 353882 and inv.period_end == sub.current_period_end
    assert mail.outbox[-1].attachments[0][0].endswith(".pdf")  # receipt with the GST invoice
    # a forged confirm is refused
    bad = client.post(
        "/app/billing/confirm/",
        {"razorpay_payment_id": "x", "razorpay_subscription_id": sid, "razorpay_signature": "nope"},
        content_type="application/json",
    )
    assert bad.status_code == 400
    # renewal webhook: next period, second invoice; a replay changes nothing
    start = sub.current_period_end
    end = billing.add_period(start, "monthly")
    charged = {
        "subscription": {
            "entity": {"id": sid, "current_start": int(start.timestamp()), "current_end": int(end.timestamp())}
        },
        "payment": {"entity": {"id": "pay_renew", "amount": 353882, "method": "upi"}},
    }
    assert hook(client, "subscription.charged", **charged).status_code == 200
    assert hook(client, "subscription.charged", **charged).status_code == 200
    with company_context(co.id):
        assert Invoice.objects.filter(company=co).count() == 2
    assert sub_of(co).current_period_end.timestamp() == int(end.timestamp())
    assert client.post("/webhooks/razorpay/", "{}", content_type="application/json").status_code == 403
    # failed renewal → overdue with grace → hold after the grace days
    set_setting("billing.grace_days", 3)
    hook(
        client,
        "subscription.pending",
        subscription={"entity": {"id": sid}},
        payment={"entity": {"amount": 353882, "error_description": "Card declined"}},
    )
    sub = sub_of(co)
    assert sub.status == Subscription.PAST_DUE and sub.failed_payments == 1 and sub.grace_until
    assert not fresh(co).billing_hold  # still working during the grace days
    with company_context(co.id):
        assert billing.run(now=timezone.now() + timedelta(days=4)) >= 1
    co = fresh(co)
    assert co.billing_hold
    # on hold: only Billing opens; the API says why; the AI does not start
    assert client.get("/app/leads/")["Location"] == "/app/billing/"
    assert client.get("/app/billing/").status_code == 200
    api = client.get("/api/v1/crm/leads/")
    assert api.status_code == 403 and api.json()["error"]["code"] == "billing_hold"
    assert "unpaid" in access.blocked(co)
    # the next successful charge lifts the hold
    charged["payment"]["entity"]["id"] = "pay_late"
    hook(client, "subscription.charged", **charged)
    assert not fresh(co).billing_hold and sub_of(co).status == Subscription.ACTIVE


@pytest.mark.django_db
def test_upgrade_prorated_downgrade_scheduled_and_cancel(client, co, owner_a, rzp):
    client.force_login(owner_a)
    _, sid = subscribe(client, co)
    sub = sub_of(co)
    now = timezone.now()
    Subscription.all_companies.filter(pk=sub.pk).update(
        current_period_start=now - timedelta(days=15), current_period_end=now + timedelta(days=15)
    )
    business = Plan.objects.get(key="business")
    with company_context(co.id):
        diff = billing.proration(fresh(co), business, "monthly", now=now)
    assert abs(diff - (999900 - 299900) // 2) < 200  # half the price difference for half the period
    r = client.post(
        "/app/billing/checkout/", {"plan": str(business.pk), "interval": "monthly"}, content_type="application/json"
    )
    order = r.json()["order_id"]
    assert r.json()["amount"] > diff  # GST on top
    client.post(
        "/app/billing/confirm/",
        {"razorpay_payment_id": "pay_up", "razorpay_order_id": order, "razorpay_signature": sign(f"{order}|pay_up")},
        content_type="application/json",
    )
    assert fresh(co).plan.key == "business"
    with company_context(co.id):
        assert Invoice.objects.filter(company=co, kind="upgrade", status=Invoice.PAID).count() == 1
    assert rzp.paths("PATCH")  # the gateway charges the new price from the next renewal
    # downgrade waits for the renewal, then applies
    r = client.post(
        "/app/billing/checkout/",
        {"plan": str(Plan.objects.get(key="starter").pk), "interval": "monthly"},
        content_type="application/json",
    )
    assert r.json()["scheduled"] and sub_of(co).pending_plan.key == "starter" and fresh(co).plan.key == "business"
    end = sub_of(co).current_period_end
    hook(
        client,
        "subscription.charged",
        subscription={
            "entity": {
                "id": sid,
                "current_start": int(end.timestamp()),
                "current_end": int((end + timedelta(days=30)).timestamp()),
            }
        },
        payment={"entity": {"id": "pay_down", "amount": 353882}},
    )
    assert fresh(co).plan.key == "starter" and sub_of(co).pending_plan is None
    # cancel: works to the period end, then hold
    assert client.post("/app/billing/", {"op": "cancel", "reason": "Too costly"}).status_code == 302
    sub = sub_of(co)
    assert sub.cancel_at_period_end and sub.cancel_reason == "Too costly"
    assert ("POST", f"/v1/subscriptions/{sid}/cancel", {"cancel_at_cycle_end": 1}) in rzp.calls
    with company_context(co.id):
        billing.run(now=sub.current_period_end + timedelta(minutes=1))
    assert sub_of(co).status == Subscription.CANCELLED and fresh(co).billing_hold


@pytest.mark.django_db
def test_trial_reminder_end_and_no_trial_registration(co, set_setting):
    with company_context(co.id):
        billing.subscription(co)
        billing.run(now=co.trial_ends_at - timedelta(days=2))
    assert any("trial ends" in m.subject for m in mail.outbox)
    assert not fresh(co).billing_hold
    with company_context(co.id):
        billing.run(now=co.trial_ends_at + timedelta(minutes=1))
    assert fresh(co).billing_hold and sub_of(co).status == Subscription.PENDING
    from apps.tenancy.services import _start_subscription

    set_setting("registration.trial_enabled", False)
    other = Company(name="No Trial", slug="no-trial")
    _start_subscription(other)
    assert other.status == Company.ACTIVE and other.billing_hold


@pytest.mark.django_db
def test_manual_invoicing_due_overdue_and_mark_paid(co, set_setting, super_admin):
    set_setting("billing.invoice_due_days", 5)
    set_setting("billing.grace_days", 2)
    now = timezone.now()
    with company_context(co.id):
        sub = billing.subscription(co)
        billing.save_terms(co, {"gateway": "manual", "custom_price": "50000"}, super_admin)
        Subscription.objects.filter(pk=sub.pk).update(
            status=Subscription.ACTIVE, current_period_start=now - timedelta(days=30), current_period_end=now
        )
        billing.run(now=now + timedelta(minutes=1))
        inv = Invoice.objects.get(company=co, status=Invoice.DUE)
        assert inv.subtotal_paise == 5000000 and inv.period_start == now and "due by" in mail.outbox[-1].subject
        billing.run(now=inv.due_at + timedelta(minutes=1))
        assert Subscription.objects.get(pk=sub.pk).status == Subscription.PAST_DUE
        billing.run(now=inv.due_at + timedelta(days=3))
        assert fresh(co).billing_hold
        billing.mark_paid(inv, "NEFT UTR 123", super_admin)
        sub = Subscription.objects.get(pk=sub.pk)
        assert sub.status == Subscription.ACTIVE and sub.current_period_end == inv.period_end
        assert not fresh(co).billing_hold and Payment.objects.get(invoice=inv).recorded_by == super_admin


# ------------------------------------------------------------------ limits, credits, features (USE-03, USE-04, SA-20)
@pytest.mark.django_db
def test_limits_overrides_credits_and_features(realty, sara, owner_a, super_admin):
    realty.plan = Plan.objects.get(key="starter")
    realty.save()
    PlanEntitlement.objects.update_or_create(plan=realty.plan, key="ai_credits", defaults={"limit_value": 10})
    PlanEntitlement.objects.update_or_create(
        plan=realty.plan, key="calls", defaults={"limit_value": 5, "enforcement": "soft", "overage_price_paise": 200}
    )
    with company_context(realty.id):
        assert limits.hard_cap(realty, "calls") is None  # soft: overage allowed
        limits.check(realty, "calls", 50)  # does not raise
        from apps.agents.models import UsageEvent

        UsageEvent.objects.create(company=realty, meter="ai_credits", quantity=10, unit="credits")
        with pytest.raises(ValidationError, match="AI credits"):
            runtime.start(sara, "web_chat")
        billing.adjust_credits(realty, 5, "Goodwill", super_admin)
        assert limits.limit(realty, "ai_credits") == 15 and access.credits_left(realty) == 5
        assert runtime.start(sara, "web_chat")  # works again with the extra credits
        assert CreditAdjustment.objects.get(company=realty).month.day == 1
        row = next(r for r in usage.overview(realty) if r["key"] == "ai_credits")
        assert row["limit"] == 15 and row["used"] == 10 and row["left"] == 5
        # SUB-04 company override beats the plan
        billing.save_terms(
            realty, {"limit_calls_mode": "custom", "limit_calls": "2", "enforcement_calls": "hard"}, super_admin
        )
        with pytest.raises(ValidationError):
            limits.check(realty, "calls", 2)
    # SA-20: a plan without campaigns removes the permission (menu, screens, API); a company override brings it back
    Plan.objects.filter(pk=realty.plan_id).update(flags={"campaigns": False, "web_chat": False})
    realty = fresh(realty)
    assert not has_perm(owner_a, "campaigns.view", realty) and has_perm(owner_a, "leads.view", realty)
    from apps.panel import menu

    assert "campaigns" not in [i["key"] for i in menu.items(owner_a, realty)]
    with company_context(realty.id):
        from apps.agents.models import AIEmployee

        with pytest.raises(ValidationError, match="Website chat"):
            runtime.start(AIEmployee.objects.get(pk=sara.pk), "web_chat")
        billing.save_terms(realty, {"feature_campaigns": "on"}, super_admin)
    assert has_perm(owner_a, "campaigns.view", fresh(realty))


@pytest.mark.django_db
def test_billing_pages_and_details(client, co, owner_a, rzp):
    client.force_login(owner_a)
    page = client.get("/app/billing/")
    assert page.status_code == 200 and b"Usage this month" in page.content and b"Free trial" in page.content
    plans = client.get("/app/billing/plans/")
    assert plans.status_code == 200 and b"Choose Starter" in plans.content
    r = client.post(
        "/app/billing/",
        {"op": "details", "legal_name": "Alpha Realty Pvt Ltd", "gstin": "29abcde1234f1z5", "state": "27"},
    )
    assert r.status_code == 302 and fresh(co).gstin == "27ABCDE1234F1Z5"  # GSTIN of another state → refused
    client.post(
        "/app/billing/",
        {"op": "details", "legal_name": "Alpha Realty Pvt Ltd", "gstin": "29abcde1234f1z5", "state": "29"},
    )
    co = fresh(co)
    assert co.gstin == "29ABCDE1234F1Z5" and co.state == "Karnataka" and co.legal_name == "Alpha Realty Pvt Ltd"
    with company_context(co.id):
        inv = billing.issue_invoice(co, "Test", 1000)
    pdf = client.get(f"/app/billing/invoices/{inv.pk}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_billing_api(client, co, owner_a, rzp):
    client.force_login(owner_a)
    s = client.get("/api/v1/billing/")
    assert (
        s.status_code == 200
        and s.json()["subscription"]["status"] == "trialing"
        and s.json()["plan"]["key"] == "starter"
    )
    assert {r["key"] for r in s.json()["usage"]} >= {"ai_credits", "calls", "users"}
    plans = client.get("/api/v1/billing/plans/").json()
    starter = next(p for p in plans if p["key"] == "starter")
    assert starter["current"] and starter["prices"]["monthly"]["total"] == 353882
    r = client.post(
        "/api/v1/billing/checkout/", {"plan": "starter", "interval": "monthly"}, content_type="application/json"
    )
    assert r.status_code == 200 and r.json()["subscription_id"] and r.json()["key"] == "rzp_test_abc"
    sid, pay = r.json()["subscription_id"], "pay_api"
    ok = client.post(
        "/api/v1/billing/confirm/",
        {"razorpay_payment_id": pay, "razorpay_subscription_id": sid, "razorpay_signature": sign(f"{pay}|{sid}")},
        content_type="application/json",
    )
    assert ok.status_code == 200 and ok.json()["invoice"].startswith("INV/")
    inv = client.get("/api/v1/billing/invoices/").json()["results"][0]
    assert inv["status"] == "paid" and client.get(f"/api/v1/billing/invoices/{inv['id']}/pdf/").status_code == 200
    assert client.get("/api/v1/billing/payments/").json()["results"][0]["status"] == "captured"
    d = client.patch("/api/v1/billing/details/", {"state": "29", "gstin": ""}, content_type="application/json")
    assert d.status_code == 200 and d.json()["state"] == "29"
    assert client.post("/api/v1/billing/cancel/", {}, content_type="application/json").json()["ends_on"]


# ------------------------------------------------------------------ Super Admin (SA-02, SA-12, SA-13, SA-14) and USE-06
@pytest.mark.django_db
def test_super_admin_billing_screens(admin_client, co, super_admin):
    starter = Plan.objects.get(key="starter")
    for url in ("/superadmin/", "/superadmin/billing/", "/superadmin/billing/?tab=invoices", "/superadmin/usage/"):
        assert admin_client.get(url).status_code == 200, url
    assert admin_client.get("/superadmin/billing/?tab=payments&status=failed").status_code == 200
    page = admin_client.get(f"/superadmin/companies/{co.pk}/billing/")
    assert page.status_code == 200 and b"Billing terms" in page.content
    # plan form: limits with overage and feature flags
    form = admin_client.get(f"/superadmin/plans/{starter.pk}/")
    assert b"Features in this plan" in form.content
    data = {
        "name": "Starter",
        "description": "",
        "gst_rate": "",
        "trial_days": "",
        "is_public": "on",
        "status": "active",
        "sort_order": 1,
        "price_monthly": "2999",
        "price_yearly": "29990",
        "features_text": "Voice + WhatsApp",
    }
    for key, _ in __import__("apps.billing.models", fromlist=["ENTITLEMENTS"]).ENTITLEMENTS:
        data[f"enforce__{key}"] = "hard"
    data.update({"limit__calls": "100", "enforce__calls": "soft", "overage__calls": "3"})
    data.update({f"feature__{k}": "on" for k, _ in __import__("apps.billing.models", fromlist=["FEATURES"]).FEATURES})
    data.pop("feature__campaigns")
    assert admin_client.post(f"/superadmin/plans/{starter.pk}/", data).status_code == 302
    starter.refresh_from_db()
    calls = starter.entitlements.get(key="calls")
    assert starter.price_yearly_paise == 2999000 and starter.flags["campaigns"] is False and starter.flags["whatsapp"]
    assert calls.limit_value == 100 and calls.enforcement == "soft" and calls.overage_price_paise == 300
    # company terms, credits, a manual invoice and marking it paid
    url = f"/superadmin/companies/{co.pk}/billing/"
    admin_client.post(url, {"op": "terms", "gateway": "manual", "custom_price": "4500", "feature_campaigns": "on"})
    admin_client.post(url, {"op": "credits", "credits": "250", "reason": "Launch bonus"})
    admin_client.post(
        url, {"op": "invoice", "description": "Onboarding", "amount": "10000", "plan": "", "interval": "monthly"}
    )
    with company_context(co.id):
        sub = Subscription.objects.get(company=co)
        assert sub.manual and sub.custom_price_paise == 450000 and sub.feature_overrides == {"campaigns": True}
        assert CreditAdjustment.objects.get(company=co).credits == 250
        inv = Invoice.objects.get(company=co, kind="manual")
    assert inv.subtotal_paise == 1000000 and inv.status == Invoice.DUE
    r = admin_client.post(
        f"/superadmin/billing/invoices/{inv.pk}/", {"op": "paid", "reference": "UTR123", "method": "bank"}
    )
    assert r.status_code == 302
    inv.refresh_from_db()
    assert inv.status == Invoice.PAID and inv.payment_ref == "UTR123"
    assert admin_client.get(f"/superadmin/billing/invoices/{inv.pk}/pdf/")["Content-Type"] == "application/pdf"
    from apps.billing import reports

    report = reports.usage_report()
    assert report["revenue"] == 1000000 and report["companies"][0]["name"] == co.name
    assert reports.dashboard()["revenue_month"] == 1000000
    # hold / release from Super Admin
    admin_client.post(url, {"op": "hold", "reason": "Overdue"})
    assert fresh(co).billing_hold
    admin_client.post(url, {"op": "release"})
    assert not fresh(co).billing_hold


@pytest.mark.django_db
def test_provider_cost_on_calls(realty, sara):
    from apps.agents.models import UsageEvent
    from apps.voice import services as voice
    from apps.voice.models import Call

    tw = Provider.objects.get(key="twilio")
    tw.config = {"account_sid": "AC1", "cost_outbound_per_min": "0.75"}
    tw.save()
    sarvam = Provider.objects.filter(vendor="sarvam").first()
    sarvam.available_models = [{"id": "saarika", "input_cost": 0.5, "output_cost": 0, "kind": "stt"}]
    sarvam.save()
    with company_context(realty.id):
        call = Call.objects.create(
            company=realty,
            employee=sara,
            direction="outbound",
            provider=tw,
            duration_sec=90,
            metrics={"providers": {"stt": json.dumps([f"{sarvam.key}/saarika"])}},
        )
        voice.finish(call)
        call.refresh_from_db()
        minutes = UsageEvent.objects.get(company=realty, meter="voice_minutes_outbound")
        stt = UsageEvent.objects.get(company=realty, meter="stt_seconds")
    assert minutes.provider_cost_paise == 150  # 2 started minutes × ₹0.75
    assert stt.provider_cost_paise == 75  # 1.5 min × ₹0.50
    assert call.cost_paise == 225
