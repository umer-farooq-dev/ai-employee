"""Security events in the audit log (SA-18)."""

from allauth.account.signals import password_changed, password_reset
from allauth.mfa.signals import authenticator_added, authenticator_removed
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from apps.audit.services import record


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record(request, "auth.login", "user", user.id, user=user, category="security")


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user:
        record(request, "auth.logout", "user", user.id, user=user, category="security")


@receiver(password_changed)
@receiver(password_reset)
def on_password(sender, request, user, **kwargs):
    record(request, "auth.password_changed", "user", user.id, user=user, category="security")


@receiver(authenticator_added)
def on_mfa_added(sender, request, user, authenticator, **kwargs):
    record(
        request, "auth.mfa_added", "user", user.id, user=user, category="security", changes={"type": authenticator.type}
    )


@receiver(authenticator_removed)
def on_mfa_removed(sender, request, user, authenticator, **kwargs):
    record(
        request,
        "auth.mfa_removed",
        "user",
        user.id,
        user=user,
        category="security",
        changes={"type": authenticator.type},
    )
