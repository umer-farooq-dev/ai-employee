"""SMS adapter (AUTH-02). The active provider is chosen in Super Admin → System Settings → SMS.

Only the development log exists until the client picks an SMS provider; that provider is added here with its
credentials entered in Super Admin (never in .env), as for every other provider.
"""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import Context, Template

from apps.platform_config import services as config

logger = logging.getLogger(__name__)


def _development_log(to, text):
    if settings.ENVIRONMENT == "production":
        raise ImproperlyConfigured("No SMS provider is configured. Choose one in Super Admin → SMS.")
    logger.warning("SMS (development log, not sent) to %s: %s", to, text)


PROVIDERS = {"log": _development_log}


def send(to: str, text: str):
    PROVIDERS[config.get("sms.provider")](to, text)


def render(setting_key: str, context: dict) -> str:
    """SMS texts are settings (e.g. sms.otp_message) rendered with the branding variables."""
    return Template(config.get(setting_key)).render(
        Context({"platform_name": config.get("general.platform_name"), **context}, autoescape=False)
    )
