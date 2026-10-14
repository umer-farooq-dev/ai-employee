"""User management used by Super Admin screens and the Admin API (SA-04, SA-18), and mobile OTP (AUTH-02)."""

import secrets
from datetime import timedelta

from allauth.account.forms import ResetPasswordForm
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.notifications import sms
from apps.platform_config import services as config

from .models import PhoneOTP

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


# ------------------------------------------------------------------ mobile OTP (AUTH-02)
def _otp_hash(otp_id, code):
    from django.utils.crypto import salted_hmac

    return salted_hmac("phone-otp", f"{otp_id}:{code}").hexdigest()


def phone_verification_required(user) -> bool:
    return bool(config.get("registration.mobile_otp_required") and not user.is_staff and not user.phone_verified_at)


def send_phone_otp(user, request=None):
    """Send a one-time code to the user's phone. Sending is limited to `otp_max_attempts` per validity window."""
    if not user.phone:
        raise ValidationError("Add a mobile number first.")
    minutes = config.get("registration.otp_valid_minutes")
    now = timezone.now()
    recent = PhoneOTP.objects.filter(user=user, created_at__gte=now - timedelta(minutes=minutes)).count()
    if recent >= config.get("registration.otp_max_attempts"):
        raise ValidationError(f"Too many codes sent. Try again in {minutes} minutes.")
    code = "".join(secrets.choice("0123456789") for _ in range(config.get("registration.otp_length")))
    otp = PhoneOTP(user=user, phone=user.phone, expires_at=now + timedelta(minutes=minutes))
    otp.code_hash = _otp_hash(otp.id, code)
    otp.save()
    sms.send(user.phone, sms.render("sms.otp_message", {"code": code, "minutes": minutes}))
    record(request, "phone.otp_sent", "user", user.id, user=user, category="security")
    return otp


def verify_phone_otp(user, code, request=None):
    otp = PhoneOTP.objects.filter(user=user, phone=user.phone, used_at__isnull=True).first()
    if not otp or otp.expires_at <= timezone.now():
        raise ValidationError("The code has expired. Send a new one.")
    if otp.attempts >= config.get("registration.otp_max_attempts"):
        raise ValidationError("Too many wrong attempts. Send a new code.")
    if not secrets.compare_digest(otp.code_hash, _otp_hash(otp.id, str(code).strip())):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        record(request, "phone.otp_failed", "user", user.id, user=user, category="security")
        raise ValidationError("Wrong code.")
    otp.used_at = user.phone_verified_at = timezone.now()
    otp.save(update_fields=["used_at"])
    user.save(update_fields=["phone_verified_at"])
    record(request, "phone.verified", "user", user.id, user=user, category="security")
