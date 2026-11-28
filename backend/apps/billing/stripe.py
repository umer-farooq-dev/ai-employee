"""Stripe (SUB-03, worldwide): hosted Checkout for subscriptions (auto-renewal) and one-time payments (prorated
upgrades, invoices), plan changes at renewal, cancel / resume, webhook signatures (SEC-13). Keys live only in
Super Admin → Payment Gateways → Stripe (live and test secret key, published key, webhook signing secret).

The API version is pinned so Stripe's yearly changes never alter the shapes read here."""

import hashlib
import hmac
import time
import urllib.parse

from apps.providers.adapters import ProviderError, request_raw

API_VERSION = "2024-06-20"
TOLERANCE = 300  # seconds a webhook signature stays valid


def provider():
    """The active Stripe provider, or None (not set up)."""
    from apps.providers.models import Provider
    from apps.providers.services import production

    from .gateways import in_use

    p = Provider.objects.filter(vendor="stripe", is_active=True).first()
    if not p:
        return None
    p = in_use(p)  # the live or the test keys, as chosen in Super Admin → Payment Gateways
    if not p.api_key or (production() and p.test_only):
        return None
    return p


def _form(data, prefix=""):
    """Nested dict / list → Stripe's form encoding (metadata[plan]=x, line_items[0][price]=y)."""
    out = []
    items = data.items() if isinstance(data, dict) else enumerate(data)
    for key, value in items:
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict | list):
            out += _form(value, name)
        elif value is not None:
            out.append((name, "true" if value is True else "false" if value is False else str(value)))
    return out


def _call(p, method, path, body=None):
    headers = {"Authorization": f"Bearer {p.api_key}", "Stripe-Version": API_VERSION}
    data = None
    if body:
        data = urllib.parse.urlencode(_form(body)).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    data_out, _ = request_raw(method, p.base_url.rstrip("/") + path, headers, data, timeout=30)
    return data_out


# ------------------------------------------------------------------ products and prices (cached on our plan)
def ensure_product(p, plan):
    ids = dict(plan.gateway_plans or {})
    if not ids.get("stripe:product"):
        ids["stripe:product"] = _call(p, "POST", "/v1/products", {"name": plan.name, "metadata": {"plan": plan.key}})[
            "id"
        ]
        plan.gateway_plans = ids
        plan.save(update_fields=["gateway_plans", "updated_at"])
    return ids["stripe:product"]


def ensure_price(p, plan, interval, currency, amount):
    """A recurring Stripe price per (plan, interval, currency, amount incl. tax); its id is kept on our plan."""
    tag = f"stripe:{currency}:{interval}:{amount}"
    if not (plan.gateway_plans or {}).get(tag):
        product = ensure_product(p, plan)
        data = _call(
            p,
            "POST",
            "/v1/prices",
            {
                "product": product,
                "currency": currency.lower(),
                "unit_amount": amount,
                "recurring": {"interval": "year" if interval == "yearly" else "month"},
                "metadata": {"plan": plan.key, "interval": interval},
            },
        )
        plan.gateway_plans = {**(plan.gateway_plans or {}), tag: data["id"]}
        plan.save(update_fields=["gateway_plans", "updated_at"])
    return plan.gateway_plans[tag]


# ------------------------------------------------------------------ checkout
def _customer(customer_id, email):
    return {"customer": customer_id} if customer_id else {"customer_email": email or None}


def checkout_subscription(p, price_id, metadata, success_url, cancel_url, customer_id="", email=""):
    return _call(
        p,
        "POST",
        "/v1/checkout/sessions",
        {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "client_reference_id": metadata.get("company"),
            "success_url": success_url,
            "cancel_url": cancel_url,
            **_customer(customer_id, email),
        },
    )


def checkout_payment(p, amount, currency, description, metadata, success_url, cancel_url, customer_id="", email=""):
    body = {
        "mode": "payment",
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": currency.lower(),
                    "unit_amount": amount,
                    "product_data": {"name": description},
                },
            }
        ],
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
        "client_reference_id": metadata.get("company"),
        "success_url": success_url,
        "cancel_url": cancel_url,
        **_customer(customer_id, email),
    }
    if not customer_id:
        body["customer_creation"] = "always"
    return _call(p, "POST", "/v1/checkout/sessions", body)


def session(p, session_id):
    return _call(p, "GET", f"/v1/checkout/sessions/{urllib.parse.quote(session_id)}")


def invoice(p, invoice_id):
    return _call(p, "GET", f"/v1/invoices/{urllib.parse.quote(invoice_id)}")


def period(inv):
    """(start, end) unix times of the subscription line of a Stripe invoice."""
    for line in (inv.get("lines") or {}).get("data") or []:
        span = line.get("period") or {}
        if span.get("start") and span.get("end"):
            return span["start"], span["end"]
    return inv.get("period_start"), inv.get("period_end")


# ------------------------------------------------------------------ subscription changes
def _schedule_id(sub):
    found = sub.get("schedule")
    return found.get("id", "") if isinstance(found, dict) else found or ""


def change_price(p, subscription_id, price_id):
    """New price from the next renewal, also when the interval changes (a subscription schedule: this period at
    the current price, then the new price; released afterwards). Upgrades are charged separately, never prorated."""
    sub = _call(p, "GET", f"/v1/subscriptions/{subscription_id}")
    current = sub["items"]["data"][0]["price"]["id"]
    sched_id = _schedule_id(sub)
    if sched_id:
        schedule = _call(p, "GET", f"/v1/subscription_schedules/{sched_id}")
    else:
        schedule = _call(p, "POST", "/v1/subscription_schedules", {"from_subscription": subscription_id})
    phase = schedule.get("current_phase") or {}
    return _call(
        p,
        "POST",
        f"/v1/subscription_schedules/{schedule['id']}",
        {
            "end_behavior": "release",
            "proration_behavior": "none",
            "phases": [
                {
                    "items": [{"price": current, "quantity": 1}],
                    "start_date": phase.get("start_date"),
                    "end_date": phase.get("end_date"),
                },
                {"items": [{"price": price_id, "quantity": 1}], "iterations": 1},
            ],
        },
    )


def set_cancel_at_period_end(p, subscription_id, cancel=True):
    """Stop (or restart) renewal at the period end; a pending plan-change schedule is released first."""
    sub = _call(p, "GET", f"/v1/subscriptions/{subscription_id}")
    if _schedule_id(sub):
        _call(p, "POST", f"/v1/subscription_schedules/{_schedule_id(sub)}/release")
    return _call(p, "POST", f"/v1/subscriptions/{subscription_id}", {"cancel_at_period_end": cancel})


# ------------------------------------------------------------------ webhooks and connection test
def verify_webhook(p, body, header, now=None):
    """Stripe-Signature: t=<time>,v1=<HMAC-SHA256 of "<time>.<body>" with the signing secret>."""
    parts = [kv.split("=", 1) for kv in (header or "").split(",") if "=" in kv]
    stamp = next((v for k, v in parts if k == "t"), "")
    signatures = [v for k, v in parts if k == "v1"]
    if not p.webhook_secret or not stamp.isdigit() or not signatures:
        raise ProviderError("Invalid webhook signature.")
    if abs((now or time.time()) - int(stamp)) > TOLERANCE:
        raise ProviderError("The webhook is too old.")
    expected = hmac.new(p.webhook_secret.encode(), f"{stamp}.{body}".encode(), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise ProviderError("Invalid webhook signature.")


def test(p, timeout=30):
    headers = {"Authorization": f"Bearer {p.api_key}", "Stripe-Version": API_VERSION}
    data, _ = request_raw("GET", p.base_url.rstrip("/") + "/v1/account", headers, None, timeout)
    name = ((data.get("settings") or {}).get("dashboard") or {}).get("display_name") or data.get("id", "")
    mode = "test mode" if p.api_key.startswith(("sk_test_", "rk_test_")) else "live mode"
    note = "" if p.webhook_secret else " · add the webhook signing secret to receive renewals"
    return f"Connected · {name} · {mode} · {str(data.get('country', '')).upper()}{note}"
