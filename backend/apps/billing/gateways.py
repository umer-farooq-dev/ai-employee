"""Payment gateways screen (Super Admin → Payment Gateways): Stripe and Razorpay, each with a live and a test set of
keys; the mode chosen decides which set charges customers. Secrets are stored encrypted on the Provider row."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.services import record
from apps.providers.adapters import ProviderError

# per gateway: the public key's config name and label, the secret's label and the prefixes that tell live from test
GATEWAYS = {
    "stripe": {
        "label": "Stripe",
        "public": "publishable_key",
        "public_label": "Published key",
        "public_hint": {"live": "pk_live_…", "test": "pk_test_…"},
        "secret_label": "API key (secret key)",  # nosec B105 — field label, not a secret
        "secret_hint": {"live": "sk_live_…", "test": "sk_test_…"},
        "secret_prefix": {"live": ("sk_live_", "rk_live_"), "test": ("sk_test_", "rk_test_")},
        "public_prefix": {"live": ("pk_live_",), "test": ("pk_test_",)},
        "webhook_hint": "whsec_…",
    },
    "razorpay": {
        "label": "Razorpay",
        "public": "key_id",
        "public_label": "Key ID",
        "public_hint": {"live": "rzp_live_…", "test": "rzp_test_…"},
        "secret_label": "Key secret",  # nosec B105 — field label, not a secret
        "secret_hint": {"live": "Razorpay → Settings → API keys", "test": "Razorpay (test mode) → API keys"},
        "secret_prefix": {},  # Razorpay key secrets have no prefix
        "public_prefix": {"live": ("rzp_live_",), "test": ("rzp_test_",)},
        "webhook_hint": "the secret you typed when adding the webhook",
    },
}
MODES = (("live", "Live"), ("test", "Test"))


def mode(p):
    return "test" if (p.config or {}).get("mode") == "test" else "live"


def in_use(p):
    """The provider with the keys of its current mode in place (in memory only): what the payment code reads."""
    spec = GATEWAYS.get(p.vendor)
    if spec and mode(p) == "test":
        cfg = p.config or {}
        p.api_key, p.webhook_secret = p.test_api_key, p.test_webhook_secret
        p.config = {**cfg, spec["public"]: cfg.get(f"test_{spec['public']}", "")}
    return p


def ready(p):
    """Has the current mode both keys?"""
    spec = GATEWAYS[p.vendor]
    live = in_use(type(p).objects.get(pk=p.pk))
    return bool(live.api_key and (live.config or {}).get(spec["public"]))


def save(p, data, files=None, user=None, request=None):
    """Active / inactive, mode, both key sets (an empty secret keeps the saved one), title and image."""
    from apps.core.uploads import save_public

    spec = GATEWAYS[p.vendor]
    cfg = dict(p.config or {})
    chosen = data.get("mode", "live")
    if chosen not in dict(MODES):
        raise ValidationError("Choose Live or Test.")
    cfg["mode"] = chosen
    cfg["title"] = str(data.get("title", "")).strip()[:80]
    for m in ("live", "test"):
        public = str(data.get(f"{m}_public", "")).strip()
        cfg[spec["public"] if m == "live" else f"test_{spec['public']}"] = public
        secret = str(data.get(f"{m}_secret", "")).strip()
        if secret:
            starts = spec["secret_prefix"].get(m)
            if starts and not secret.startswith(starts):
                raise ValidationError(f"The {m} {spec['secret_label']} should start with {' or '.join(starts)}.")
            setattr(p, "api_key" if m == "live" else "test_api_key", secret)
        hook = str(data.get(f"{m}_webhook", "")).strip()
        if hook:
            setattr(p, "webhook_secret" if m == "live" else "test_webhook_secret", hook)
        if public and not public.startswith(spec["public_prefix"][m]):
            raise ValidationError(f"The {m} {spec['public_label']} should start with {spec['public_prefix'][m][0]}.")
    image = (files or {}).get("image")
    if image:
        p.logo = save_public(image, "gateways")
    p.config = cfg
    p.is_active = data.get("active") == "on"
    p.save()
    if p.is_active and not ready(p):
        raise ValidationError(
            f"Saved, but the {chosen} keys are missing: add the {spec['secret_label'].lower()} and "
            f"the {spec['public_label'].lower()} to take payments."
        )
    record(
        request, "payment_gateway.save", "provider", p.key, user=user, changes={"active": p.is_active, "mode": chosen}
    )
    return p


def check(p):
    """A free call with the keys in use → health {"ok", "message"} (also stored on the provider)."""
    from . import razorpay, stripe

    live = in_use(type(p).objects.get(pk=p.pk))
    try:
        if not live.api_key:
            raise ProviderError(f"No {mode(p)} key saved.")
        message = (stripe.test if p.vendor == "stripe" else razorpay.test)(live)
        health = {"ok": True, "message": message}
    except ProviderError as exc:
        health = {"ok": False, "message": str(exc)}
    p.health = {**health, "checked_at": timezone.now().isoformat()}
    p.save(update_fields=["health", "updated_at"])
    return health
