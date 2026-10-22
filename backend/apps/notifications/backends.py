"""SA-10: every e-mail (templates, sign-in, password reset) goes out through the e-mail provider switched on in Super
Admin → Voice & Channels (SMTP: works with SES, SendGrid, Brevo, Zoho, Google Workspace …). With none switched on,
the infrastructure fallback from .env (the local mail catcher in development) is used."""

from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend


def _provider():
    from apps.providers.models import Provider

    return Provider.objects.filter(vendor="smtp", is_active=True, capabilities__contains=["email"]).first()


def smtp_connection(provider, timeout=20, **kwargs):
    cfg = provider.config or {}
    security = cfg.get("security", "tls")
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend",
        host=cfg.get("host", ""),
        port=int(cfg.get("port") or (465 if security == "ssl" else 587)),
        username=cfg.get("username", ""),
        password=provider.api_key,
        use_tls=security == "tls",
        use_ssl=security == "ssl",
        timeout=timeout,
        **kwargs,
    )


class ProviderEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        provider = _provider()
        if provider:
            sender = (provider.config or {}).get("from_address", "").strip()
            if sender:  # the provider's verified sender address, keeping the sender name
                for m in email_messages:
                    m.from_email = formataddr((parseaddr(m.from_email)[0], sender))
            backend = smtp_connection(provider, fail_silently=self.fail_silently)
        else:
            backend = get_connection(settings.EMAIL_FALLBACK_BACKEND, fail_silently=self.fail_silently)
        return backend.send_messages(email_messages)
