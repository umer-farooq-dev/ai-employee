"""SMS adapter (AUTH-02, SA-10). The provider with the SMS capability switched on in Super Admin → Voice & Channels
sends (MSG91, or Twilio with an SMS sender number); credentials live only there. With none switched on, development
servers write the message to the log and production refuses.
"""

import logging
import urllib.parse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import Context, Template

from apps.platform_config import services as config

logger = logging.getLogger(__name__)


def _development_log(to, text):
    if settings.ENVIRONMENT == "production":
        raise ImproperlyConfigured("No SMS provider is switched on. Add one in Super Admin → Voice & Channels.")
    logger.warning("SMS (development log, not sent) to %s: %s", to, text)


def _msg91(provider, to, text):
    from apps.providers.adapters import _request
    from apps.providers.vendors import _cfg

    _request(
        "POST",
        provider.base_url.rstrip("/") + "/api/v2/sendsms",
        {"authkey": provider.api_key},
        {
            "sender": _cfg(provider, "sender"),
            "route": _cfg(provider, "route") or "4",
            "country": "0",
            "DLT_TE_ID": _cfg(provider, "dlt_template_id"),
            "sms": [{"message": text, "to": [to.lstrip("+")]}],
        },
        timeout=20,
    )


def _twilio(provider, to, text):
    from apps.providers.adapters import request_raw
    from apps.providers.vendors import _basic, _cfg

    sid = _cfg(provider, "account_sid")
    body = urllib.parse.urlencode({"To": to, "From": _cfg(provider, "sms_from"), "Body": text}).encode()
    request_raw(
        "POST",
        f"{provider.base_url.rstrip('/')}/2010-04-01/Accounts/{sid}/Messages.json",
        {**_basic(sid, provider.api_key), "Content-Type": "application/x-www-form-urlencoded"},
        body,
        20,
    )


SENDERS = {"msg91": _msg91, "twilio": _twilio}


def provider():
    from apps.providers.models import Provider

    return (
        Provider.objects.filter(is_active=True, capabilities__contains=["sms"], vendor__in=list(SENDERS))
        .order_by("sort_order")
        .first()
    )


def send(to: str, text: str):
    p = provider()
    if p:
        SENDERS[p.vendor](p, to, text)
    else:
        _development_log(to, text)


def render(setting_key: str, context: dict) -> str:
    """SMS texts are settings (e.g. sms.otp_message) rendered with the branding variables."""
    return Template(config.get(setting_key)).render(
        Context({"platform_name": config.get("general.platform_name"), **context}, autoescape=False)
    )
