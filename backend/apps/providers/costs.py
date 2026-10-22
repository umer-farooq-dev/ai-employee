"""USE-06: what each call and message costs us at the provider, from the prices entered in Super Admin (platform
currency, rupees): speech models per minute / per 1M characters (model list), telephony per minute and WhatsApp per
message category (the provider's key popup). Stored in paise on the usage rows for the margin reports."""

from .models import Provider

TELEPHONY_PRICES = [
    ("cost_inbound_per_min", "Cost per inbound minute (₹, for margin reports)", "0.00", False),
    ("cost_outbound_per_min", "Cost per outbound minute (₹, for margin reports)", "0.00", False),
]
WHATSAPP_PRICES = [
    ("cost_marketing", "Cost per marketing message (₹)", "0.00", False),
    ("cost_utility", "Cost per utility message (₹)", "0.00", False),
    ("cost_authentication", "Cost per authentication message (₹)", "0.00", False),
    ("cost_service", "Cost per service message (₹)", "0.00", False),
]


def _float(value):
    try:
        return max(float(str(value).strip() or 0), 0.0)
    except ValueError:
        return 0.0


def config_price(provider, name):
    """Rupees from the provider's config (0 when not entered)."""
    return _float((provider.config or {}).get(name)) if provider else 0.0


def model_price(described):
    """'sarvam/saarika' → the model's input_cost (rupees); a bare provider key uses its first speech model."""
    key, _, model = str(described or "").partition("/")
    provider = Provider.objects.filter(key=key).only("available_models").first()
    rows = provider.available_models if provider else []
    row = next((m for m in rows if m.get("id") == model), None) or (rows[0] if rows and not model else None)
    return _float((row or {}).get("input_cost"))


def paise(rupees):
    return round(rupees * 100, 2)
