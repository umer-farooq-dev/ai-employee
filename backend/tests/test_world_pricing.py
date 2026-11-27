"""Worldwide pricing: visitor country → currency, plan prices per currency, export invoices without GST, Stripe
checkout / return / webhooks (faked, no network; webhook signatures are real HMACs)."""

import hashlib
import hmac
import io
import json
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from pypdf import PdfReader

from apps.billing import currency, stripe
from apps.billing import services as billing
from apps.billing.models import Currency, Invoice, Payment, Plan, PlanPrice, Subscription
from apps.providers.models import Provider
from apps.tenancy.context import company_context
from apps.tenancy.models import Company

HOOK = "whsec_test"


@pytest.fixture
def rates(db):
    """1 INR = 0.012 USD = 3.35 PKR; USD charged through Stripe."""
    for code, rate in (("USD", "0.012"), ("PKR", "3.35"), ("JPY", "1.8")):
        Currency.objects.filter(code=code).update(is_active=True, rate=Decimal(rate), gateway=Currency.STRIPE)


class FakeStripe:
    def __init__(self, monkeypatch):
        self.calls, self.sessions, self.n = [], {}, 0
        monkeypatch.setattr(stripe, "_call", self.call)

    def call(self, p, method, path, body=None):
        self.calls.append((method, path, body))
        self.n += 1
        if path == "/v1/checkout/sessions":
            sid = f"cs_{self.n}"
            self.sessions[sid] = {"id": sid, "url": f"https://checkout.stripe.com/c/{sid}", **(body or {})}
            return self.sessions[sid]
        if path.startswith("/v1/checkout/sessions/"):
            return self.sessions[path.rsplit("/", 1)[1]]
        if path.startswith("/v1/invoices/"):
            now = int(time.time())
            return {
                "id": path.rsplit("/", 1)[1],
                "lines": {"data": [{"period": {"start": now, "end": now + 30 * 86400}}]},
            }
        if path.startswith("/v1/subscriptions/") and method == "GET":
            return {
                "id": path.rsplit("/", 1)[1],
                "schedule": None,
                "items": {"data": [{"id": "si_1", "price": {"id": "price_old"}}]},
            }
        if path == "/v1/subscription_schedules":
            return {"id": "sub_sched_1", "current_phase": {"start_date": 1, "end_date": 2}, "phases": []}
        prefix = {"/v1/products": "prod", "/v1/prices": "price"}.get(path, "obj")
        return {"id": f"{prefix}_{self.n}"}

    def complete(self, sid, **extra):
        s = self.sessions[sid]
        s.update({"status": "complete", "payment_status": "paid", "customer": "cus_9", **extra})
        return s


@pytest.fixture
def fake_stripe(db, monkeypatch, rates):
    p = Provider.objects.get(key="stripe")
    p.api_key, p.webhook_secret, p.is_active = "sk_test_abc", HOOK, True
    p.save()
    return FakeStripe(monkeypatch)


@pytest.fixture
def us_co(company_a, owner_a, rates):
    company_a.plan = Plan.objects.get(key="starter")
    company_a.status, company_a.trial_ends_at = Company.TRIAL, timezone.now() + timedelta(days=10)
    company_a.country, company_a.currency, company_a.email = "US", "USD", "billing@alpha.example"
    company_a.save()
    return company_a


def signed(payload, secret=HOOK, stamp=None):
    body = json.dumps(payload)
    stamp = stamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{stamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return body, f"t={stamp},v1={sig}"


def test_currency_reference_data_formatting_and_rounding(rates):
    assert currency.country_currency("PK") == "PKR" and currency.country_currency("US") == "USD"
    assert currency.fmt(299900, "INR") == "₹2,999.00"
    assert currency.fmt(29990000, "INR", decimals=False) == "₹2,99,900"
    assert currency.fmt(4900, "USD", decimals=False) == "$49"
    assert currency.fmt(990000, "PKR", decimals=False) == "Rs 9,900"
    assert currency.fmt(5400, "JPY", decimals=False) == "¥5,400"
    assert currency.nice(Decimal("35.98")) == 36 and currency.nice(Decimal("10046.65")) == 10000
    # ₹2,999 → $36 and Rs 10,000 at today's rate; a fixed price wins over the rate
    plan = Plan.objects.get(key="starter")
    assert currency.plan_amount(plan, "monthly", "USD") == 3600
    assert currency.plan_amount(plan, "monthly", "PKR") == 1000000
    PlanPrice.objects.create(plan=plan, currency="USD", monthly_paise=4900)
    assert currency.plan_amount(plan, "monthly", "USD") == 4900
    # countries: their own currency when offered, else the fallback (USD), else the base currency
    assert currency.for_country("PK") == "PKR" and currency.for_country("DE") == "USD"
    Currency.objects.filter(code="USD").update(rate=None)
    assert currency.for_country("DE") == "INR"


def test_website_prices_follow_the_visitor(client, rates):
    india = client.get("/pricing/").content.decode()
    assert "₹2,999" in india
    us = client.get("/pricing/", HTTP_CF_IPCOUNTRY="US").content.decode()
    assert "$36" in us and "₹2,999" not in us and "Prices in" not in us
    picked = client.get("/pricing/?currency=PKR", HTTP_CF_IPCOUNTRY="US")
    assert "Rs 10,000" in picked.content.decode() and picked.cookies["currency"].value == "PKR"
    assert "Rs 10,000" in client.get("/pricing/", HTTP_CF_IPCOUNTRY="US").content.decode()  # remembered
    region = client.get("/pricing/?region=JP")
    assert "¥5,400" in region.content.decode() and region.cookies["region"].value == "JP"


def test_registration_from_abroad_bills_in_the_local_currency(client, rates, set_setting):
    set_setting("registration.approval_required", False)
    from apps.industries.models import Industry

    r = client.post(
        "/accounts/signup/",
        {
            "email": "owner@acme.example",
            "password1": "S3cure-pass-word!",
            "password2": "S3cure-pass-word!",
            "business_name": "Acme Homes",
            "full_name": "Pat Doe",
            "phone": "+12025550123",
            "industry": Industry.objects.filter(is_active=True).first().key,
            "country": "US",
            "city": "Austin",
            "state": "Texas",
            "gstin": "27ABCDE1234F1Z5",
            "accept_terms": "on",
        },
    )
    assert r.status_code == 302, r.content
    company = Company.objects.get(name="Acme Homes")
    assert (company.country, company.currency, company.state, company.gstin) == ("US", "USD", "Texas", "")


def test_export_invoice_has_no_gst_and_reads_in_dollars(us_co, set_setting):
    set_setting("billing.seller_state", "27")
    with company_context(us_co.id):
        q = billing.plan_quote(us_co, us_co.plan, "monthly")
        assert q == {**q, "taxable": 3600, "total": 3600, "domestic": False, "currency": "USD"}
        inv = billing.manual_invoice(us_co, "Setup", 4950, notify=False)
    assert (inv.currency, inv.domestic, inv.total_paise, inv.place_of_supply) == ("USD", False, 4950, "United States")
    assert "export" in inv.notes.lower()
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(billing.invoice_pdf(inv))).pages)
    assert "INVOICE" in text and "TAX INVOICE" not in text and "CGST" not in text and "IGST @" not in text
    assert "$49.50" in text and "US dollars Forty Nine and 50/100 Only" in text


def test_stripe_subscribe_return_renew_fail_and_cancel(client, us_co, owner_a, fake_stripe):
    client.force_login(owner_a)
    plan = us_co.plan
    r = client.post(
        "/app/billing/checkout/", {"plan": str(plan.pk), "interval": "monthly"}, content_type="application/json"
    )
    assert r.status_code == 200, r.content
    out = r.json()
    assert out["gateway"] == "stripe" and out["url"].startswith("https://checkout.stripe.com/")
    sid = out["url"].rsplit("/", 1)[1]
    session = fake_stripe.sessions[sid]
    assert session["mode"] == "subscription" and session["metadata"]["company"] == str(us_co.pk)
    price = next(b for m, p, b in fake_stripe.calls if p == "/v1/prices")
    assert price["currency"] == "usd" and price["unit_amount"] == 3600 and price["recurring"] == {"interval": "month"}
    # not paid yet: nothing changes
    assert client.get(f"/app/billing/return/?session_id={sid}").status_code == 302
    assert Company.objects.get(pk=us_co.pk).status == Company.TRIAL
    # paid: back from Stripe → active, USD invoice without GST
    fake_stripe.complete(sid, subscription="sub_123", invoice="in_1")
    client.get(f"/app/billing/return/?session_id={sid}")
    co = Company.objects.get(pk=us_co.pk)
    assert co.status == Company.ACTIVE
    with company_context(co.id):
        sub = Subscription.objects.get(company=co)
        assert (sub.gateway, sub.gateway_subscription_id, sub.gateway_customer_id) == ("stripe", "sub_123", "cus_9")
        inv = Invoice.objects.get(company=co)
        assert (inv.currency, inv.total_paise, inv.domestic, inv.payment_ref) == ("USD", 3600, False, "in_1")
    # the webhook for the same checkout changes nothing
    body, sig = signed({"type": "checkout.session.completed", "data": {"object": fake_stripe.sessions[sid]}})
    assert (
        client.post("/webhooks/stripe/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig).content
        == b"ignored"
    )
    # forged and stale signatures are refused
    assert (
        client.post(
            "/webhooks/stripe/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=x"
        ).status_code
        == 403
    )
    _, old = signed({}, stamp=int(time.time()) - 3600)
    assert (
        client.post("/webhooks/stripe/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=old).status_code
        == 403
    )
    # renewal
    now = int(time.time()) + 30 * 86400
    renewal = {
        "id": "in_2",
        "subscription": "sub_123",
        "billing_reason": "subscription_cycle",
        "amount_paid": 3600,
        "currency": "usd",
        "lines": {"data": [{"period": {"start": now, "end": now + 30 * 86400}}]},
    }
    body, sig = signed({"type": "invoice.paid", "data": {"object": renewal}})
    assert (
        client.post("/webhooks/stripe/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig).content
        == b"charged"
    )
    with company_context(co.id):
        assert Invoice.objects.filter(company=co, currency="USD").count() == 2
    # failed renewal → overdue with grace
    failed = {"id": "in_3", "subscription": "sub_123", "amount_due": 3600, "currency": "usd"}
    body, sig = signed({"type": "invoice.payment_failed", "data": {"object": failed}})
    assert (
        client.post("/webhooks/stripe/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig).content
        == b"past due"
    )
    with company_context(co.id):
        sub = Subscription.objects.get(company=co)
        assert sub.status == Subscription.PAST_DUE and sub.grace_until
        assert Payment.objects.filter(company=co, status=Payment.FAILED, currency="USD").exists()
        sub.status = Subscription.ACTIVE
        sub.save()
    # a downgrade waits for the renewal: a schedule keeps this period at the old price, then the new one
    PlanPrice.objects.create(plan=Plan.objects.get(key="business"), currency="USD", monthly_paise=9900)
    with company_context(co.id):
        Subscription.objects.filter(company=co).update(current_period_start=timezone.now() - timedelta(days=1))
        co.plan = Plan.objects.get(key="business")
        co.save(update_fields=["plan"])
    r = client.post(
        "/app/billing/checkout/", {"plan": str(plan.pk), "interval": "monthly"}, content_type="application/json"
    )
    assert r.status_code == 200 and "scheduled" in r.json(), r.content
    update = next(b for m, p, b in fake_stripe.calls if p == "/v1/subscription_schedules/sub_sched_1")
    assert update["end_behavior"] == "release" and update["phases"][0]["items"][0]["price"] == "price_old"
    assert update["phases"][1]["iterations"] == 1
    # cancel → Stripe keeps it until the period ends; resume → renews again
    assert client.post("/app/billing/", {"op": "cancel", "reason": "test"}).status_code == 302
    assert ("POST", "/v1/subscriptions/sub_123", {"cancel_at_period_end": True}) in fake_stripe.calls
    r = client.post("/app/billing/checkout/", {"what": "resume"}, content_type="application/json")
    assert r.json() == {"resumed": True}
    assert ("POST", "/v1/subscriptions/sub_123", {"cancel_at_period_end": False}) in fake_stripe.calls
    # the subscription ends at Stripe
    with company_context(co.id):
        Subscription.objects.filter(company=co).update(current_period_end=timezone.now() - timedelta(minutes=1))
    body, sig = signed({"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_123"}}})
    client.post("/webhooks/stripe/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig)
    assert Company.objects.get(pk=co.pk).billing_hold


def test_super_admin_currencies_plan_prices_and_company_terms(admin_client, us_co, fake_stripe, monkeypatch):
    page = admin_client.get("/superadmin/billing/currencies/")
    assert page.status_code == 200 and b"/webhooks/stripe/" in page.content
    r = admin_client.post(
        "/superadmin/billing/currencies/",
        {"codes": ["EUR"], "active_EUR": "on", "rate_EUR": "0.011", "manual_EUR": "on", "gateway_EUR": "stripe"},
    )
    assert r.status_code == 302
    eur = Currency.objects.get(code="EUR")
    assert eur.is_active and eur.rate == Decimal("0.011") and eur.manual_rate
    # the rates button: manual rates are kept
    from apps.providers import adapters

    monkeypatch.setattr(adapters, "_request", lambda *a, **k: {"rates": {"USD": 0.0119, "EUR": 0.5}})
    admin_client.post("/superadmin/billing/currencies/", {"op": "refresh"})
    assert Currency.objects.get(code="USD").rate == Decimal("0.011900") and Currency.objects.get(
        code="EUR"
    ).rate == Decimal("0.011")
    # a fixed price per currency on the plan
    plan = Plan.objects.get(key="starter")
    form = admin_client.get(f"/superadmin/plans/{plan.pk}/")
    assert form.status_code == 200 and b"Prices in other currencies" in form.content
    data = {
        "name": plan.name,
        "description": plan.description,
        "price_monthly": "2999",
        "price_yearly": "29990",
        "status": "active",
        "sort_order": plan.sort_order,
        "is_public": "on",
        "cp0_currency": "USD",
        "cp0_monthly": "49",
        "cp0_yearly": "490",
    }
    r = admin_client.post(f"/superadmin/plans/{plan.pk}/", data)
    assert r.status_code == 302, r.content
    assert PlanPrice.objects.get(plan=plan, currency="USD").monthly_paise == 4900
    # company terms: currency locked under a running auto-renewal, free otherwise
    with company_context(us_co.id):
        sub = billing.subscription(us_co)
        sub.status, sub.gateway, sub.gateway_subscription_id = Subscription.ACTIVE, "stripe", "sub_9"
        sub.current_period_end = timezone.now() + timedelta(days=5)
        sub.save()
    admin_client.post(
        f"/superadmin/companies/{us_co.pk}/billing/", {"op": "terms", "gateway": "stripe", "currency": "PKR"}
    )
    assert Company.objects.get(pk=us_co.pk).currency == "USD"
    with company_context(us_co.id):
        Subscription.objects.filter(company=us_co).update(gateway_subscription_id="")
    admin_client.post(
        f"/superadmin/companies/{us_co.pk}/billing/",
        {"op": "terms", "gateway": "stripe", "currency": "PKR", "country": "PK"},
    )
    co = Company.objects.get(pk=us_co.pk)
    assert (co.currency, co.country) == ("PKR", "PK")
