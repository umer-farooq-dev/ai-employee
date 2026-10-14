from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.internal import ratelimit
from allauth.mfa.adapter import DefaultMFAAdapter
from django.contrib import messages
from django.shortcuts import redirect

from apps.audit.services import record
from apps.core import crypto
from apps.notifications import services as mail
from apps.platform_config import services as config


def lockout_config():
    """AUTH-06 rate for allauth's login_failed limiter, built from Super Admin → Security."""
    attempts = config.get("security.lockout_attempts")
    seconds = config.get("security.lockout_minutes") * 60
    return {"login_failed": f"{attempts}/{seconds}s/ip,{attempts}/{seconds}s/key"}


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # Company registration (AUTH-01) is built in Phase 2; it will honour the `registration.enabled` setting.
        return False

    def pre_authenticate(self, request, **credentials):
        """AUTH-06: lockout after N failed attempts per account and per IP; N and duration come from Super Admin."""
        self._login_failed_rl_usage = ratelimit.consume(
            request,
            config=lockout_config(),
            action="login_failed",
            key=self._get_login_attempts_cache_key(request, **credentials),
        )
        if not self._login_failed_rl_usage:
            record(request, "auth.locked_out", "user", credentials.get("email", ""), category="security")
            raise self.validation_error("too_many_login_attempts")

    def authentication_failed(self, request, **credentials):
        record(request, "auth.login_failed", "user", credentials.get("email", ""), category="security")

    def pre_login(self, request, user, **kwargs):
        """TEN-06: members of a suspended company cannot sign in (staff are never company members)."""
        from apps.tenancy.models import Company, Membership

        memberships = Membership.all_companies.filter(user=user, status=Membership.ACTIVE)
        if (
            not user.is_staff
            and memberships.exists()
            and not memberships.exclude(company__status=Company.SUSPENDED).exists()
        ):
            record(request, "auth.login_blocked_suspended", "user", user.id, category="security", user=user)
            messages.error(request, "Your company account is suspended. Please contact support.")
            return redirect("account_login")
        return super().pre_login(request, user, **kwargs)

    def get_from_email(self):
        return mail.from_email()

    def send_mail(self, template_prefix, email, context):
        """NOTI-01: use the editable database template when one exists."""
        context = {k: v for k, v in context.items() if k != "request"}
        if not mail.send(template_prefix, email, context):
            super().send_mail(template_prefix, email, context)


class MFAAdapter(DefaultMFAAdapter):
    """SEC-07: TOTP secrets and recovery seeds are encrypted at rest."""

    def encrypt(self, text):
        return crypto.encrypt(text)

    def decrypt(self, encrypted_text):
        return crypto.decrypt(encrypted_text)
