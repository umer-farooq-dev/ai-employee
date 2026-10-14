"""Security middleware driven by Super Admin settings (AUTH-03, AUTH-05, SA-18, SA-27)."""

import ipaddress
import time

from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from apps.core.request import client_ip
from apps.platform_config import services as config
from apps.tenancy.middleware import PLATFORM_PATHS
from apps.tenancy.services import IMPERSONATOR_SESSION_KEY

# Paths a user must still reach while being forced to set up 2FA or during maintenance.
OPEN_PATHS = ("/accounts/", "/static/", "/media/", "/healthz/", "/api/v1/auth/", "/superadmin/")


def _is_api(request):
    return request.path.startswith(("/api/", "/public/"))


class SessionSecurityMiddleware:
    """AUTH-03 inactivity timeout from settings (remember-me only controls the cookie lifetime),
    and the impersonating staff user on request.impersonator."""

    LAST_ACTIVITY = "last_activity"
    WRITE_EVERY = 60  # seconds; avoid saving the session on every single request

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        if request.user.is_authenticated:
            now = int(time.time())
            last = request.session.get(self.LAST_ACTIVITY)
            if last and now - last > config.get("security.session_timeout_minutes") * 60:
                logout(request)
                if _is_api(request):
                    return JsonResponse(
                        {"error": {"code": "session_expired", "message": "Session expired."}}, status=401
                    )
                return redirect(f"{settings.LOGIN_URL}?next={request.path}")
            if not last or now - last >= self.WRITE_EVERY:
                request.session[self.LAST_ACTIVITY] = now
            staff_id = request.session.get(IMPERSONATOR_SESSION_KEY)
            if staff_id:
                request.impersonator = get_user_model().objects.filter(id=staff_id, is_staff=True).first()
        return self.get_response(request)


class AdminIPAllowlistMiddleware:
    """SA-18: Super Admin and the Admin API only from allowed IPs (empty list = no restriction)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(PLATFORM_PATHS):
            allowed = config.get("security.admin_ip_allowlist")
            if allowed and not self._allowed(client_ip(request), allowed):
                return HttpResponseForbidden("Access from this IP address is not allowed.")
        return self.get_response(request)

    @staticmethod
    def _allowed(raw_ip, allowed):
        """Unknown or malformed client IP = not allowed (fail closed)."""
        try:
            ip = ipaddress.ip_address(raw_ip or "")
        except ValueError:
            return False
        return any(ip in ipaddress.ip_network(net, strict=False) for net in allowed)


class Require2FAMiddleware:
    """AUTH-05: staff must use 2FA (setting); company users must when the platform or their company enforces it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not request.impersonator and self._required(request) and not self._has_2fa(user):
            if not request.path.startswith(("/accounts/", "/static/", "/media/", "/api/v1/auth/")):
                if _is_api(request):
                    return JsonResponse(
                        {
                            "error": {
                                "code": "mfa_required",
                                "message": "Set up two-factor " "authentication to continue.",
                            }
                        },
                        status=403,
                    )
                return redirect("mfa_activate_totp")
        return self.get_response(request)

    @staticmethod
    def _required(request):
        if request.user.is_staff:
            return config.get("security.staff_2fa_required")
        company = getattr(request, "company", None)
        return bool(company and (company.require_2fa or config.get("security.company_2fa_enforced")))

    @staticmethod
    def _has_2fa(user):
        from allauth.mfa.models import Authenticator

        return Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists()


class TimezoneMiddleware:
    """Display times in the user's timezone, else the company's, else the platform default (SA-25)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from zoneinfo import ZoneInfo

        from django.utils import timezone

        user = request.user
        company = getattr(request, "company", None)
        name = (
            (user.timezone if user.is_authenticated else "")
            or (company.timezone if company else "")
            or config.get("locale.timezone")
        )
        timezone.activate(ZoneInfo(name))
        return self.get_response(request)


class MaintenanceMiddleware:
    """SA-27: website and company panel show the maintenance page; Super Admin and staff keep working."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            config.get("maintenance.enabled")
            and not request.path.startswith(OPEN_PATHS + PLATFORM_PATHS)
            and not (request.user.is_authenticated and request.user.is_staff)
        ):
            if _is_api(request):
                return JsonResponse(
                    {"error": {"code": "maintenance", "message": "Maintenance in progress."}}, status=503
                )
            return render(
                request,
                "website/maintenance.html",
                {"maintenance_message": config.get("maintenance.message")},
                status=503,
            )
        return self.get_response(request)
