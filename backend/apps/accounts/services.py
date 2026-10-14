"""User management used by Super Admin screens and the Admin API (SA-04, SA-18)."""

from allauth.account.forms import ResetPasswordForm
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record

User = get_user_model()


@transaction.atomic
def create_user(email, full_name="", phone="", is_staff=False, platform_role=None, request=None, send_invite=True):
    """Create a user without a password; they set it through the emailed reset link (no passwords in transit)."""
    email = email.lower().strip()
    if User.objects.filter(email=email).exists():
        raise ValidationError("A user with this email already exists.")
    user = User.objects.create_user(
        email, password=None, full_name=full_name, phone=phone, is_staff=is_staff, platform_role=platform_role
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
    record(
        request,
        "user.create",
        "user",
        user.id,
        changes={"email": email, "is_staff": is_staff},
        category="security" if is_staff else "general",
    )
    if send_invite and request is not None:
        send_password_reset(user, request)
    return user


def send_password_reset(user, request):
    form = ResetPasswordForm(data={"email": user.email})
    if form.is_valid():
        form.save(request)
    record(request, "user.password_reset_sent", "user", user.id, category="security")


def set_active(user, active, request=None):
    """Lock / unlock (SA-04). Locking ends all sessions; unlocking clears failed-login lockouts."""
    user.is_active = active
    user.save(update_fields=["is_active"])
    if not active:
        end_sessions(user, request=request, audit=False)
    elif request is not None:  # unlocking also clears failed-login lockouts for this account
        from allauth.account.adapter import get_adapter
        from allauth.core.internal import ratelimit

        from .adapter import lockout_config

        key = get_adapter(request)._get_login_attempts_cache_key(request, email=user.email)
        ratelimit.clear(request, config=lockout_config(), action="login_failed", key=key)
    record(request, "user.unlock" if active else "user.lock", "user", user.id, category="security")


def reset_2fa(user, request=None):
    deleted, _ = Authenticator.objects.filter(user=user).delete()
    record(request, "user.reset_2fa", "user", user.id, category="security", changes={"removed": deleted})


def end_sessions(user, request=None, audit=True):
    sessions = UserSession.objects.filter(user=user)
    count = 0
    for session in sessions:
        session.end()
        count += 1
    if audit:
        record(request, "user.end_sessions", "user", user.id, category="security", changes={"sessions": count})
    return count
