"""Razorpay (SUB-03): plans, subscriptions (auto-renewal), one-time orders (prorated upgrades, invoice payments),
checkout and webhook signatures (SEC-13). Keys live only in Super Admin → Voice & Channels → Razorpay
(key id in the config, key secret as the provider key, webhook secret)."""

import hashlib
import hmac

from apps.providers.adapters import ProviderError, _request
from apps.providers.vendors import _basic, _cfg

CHECKOUT_JS = "https://checkout.razorpay.com/v1/checkout.js"


def provider():
    """The active payment provider, or None (online payment not set up)."""
    from apps.providers.models import Provider
    from apps.providers.services import production

    p = Provider.objects.filter(vendor="razorpay", is_active=True).first()
    if not p or not p.api_key or not _cfg(p, "key_id") or (production() and p.test_only):
        return None
    return p


def _call(p, method, path, body=None):
    return _request(method, p.base_url.rstrip("/") + path, _basic(_cfg(p, "key_id"), p.api_key), body, timeout=30)


def key_id(p):
    return _cfg(p, "key_id")


def ensure_plan(p, plan, interval, amount_paise):
    """A Razorpay plan per (our plan, interval, amount incl. GST); its id is kept on our plan."""
    tag = f"{interval}:{amount_paise}"
    ids = dict(plan.gateway_plans or {})
    if ids.get(tag):
        return ids[tag]
    data = _call(
        p,
        "POST",
        "/v1/plans",
        {
            "period": "monthly" if interval == "monthly" else "yearly",
            "interval": 1,
            "item": {"name": f"{plan.name} ({interval})", "amount": amount_paise, "currency": "INR"},
            "notes": {"plan": plan.key},
        },
    )
    ids[tag] = data["id"]
    plan.gateway_plans = ids
    plan.save(update_fields=["gateway_plans", "updated_at"])
    return data["id"]


def create_subscription(p, plan_id, interval, notes, start_at=None):
    body = {
        "plan_id": plan_id,
        "total_count": 120 if interval == "monthly" else 10,
        "customer_notify": 1,
        "notes": notes,
    }
    if start_at:
        body["start_at"] = int(start_at.timestamp())
    return _call(p, "POST", "/v1/subscriptions", body)


def update_subscription(p, subscription_id, plan_id):
    """New price from the next renewal (downgrades and the renewal price after an upgrade)."""
    return _call(
        p, "PATCH", f"/v1/subscriptions/{subscription_id}", {"plan_id": plan_id, "schedule_change_at": "cycle_end"}
    )


def cancel_subscription(p, subscription_id, at_cycle_end=True):
    return _call(p, "POST", f"/v1/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": int(at_cycle_end)})


def create_order(p, amount_paise, receipt, notes):
    return _call(
        p, "POST", "/v1/orders", {"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes}
    )


def _sign(secret, message):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_payment(p, payment_id, signature, order_id="", subscription_id=""):
    """Checkout handler signature: order → order_id|payment_id; subscription → payment_id|subscription_id."""
    message = f"{order_id}|{payment_id}" if order_id else f"{payment_id}|{subscription_id}"
    if not signature or not hmac.compare_digest(_sign(p.api_key, message), signature):
        raise ProviderError("The payment signature does not match.")


def verify_webhook(p, body, signature):
    if not p.webhook_secret or not signature or not hmac.compare_digest(_sign(p.webhook_secret, body), signature):
        raise ProviderError("Invalid webhook signature.")


def test(p, timeout=30):
    data = _request(
        "GET", p.base_url.rstrip("/") + "/v1/plans?count=1", _basic(_cfg(p, "key_id"), p.api_key), None, timeout
    )
    mode = "test mode" if _cfg(p, "key_id").startswith("rzp_test_") else "live mode"
    note = "" if p.webhook_secret else " · add the webhook secret to receive renewals"
    return f"Connected · {mode} · {data.get('count', 0)} plan(s){note}"
