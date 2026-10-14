"""Base classes every API view uses: tenant context for Bearer-token (app) clients, permission checks, audit."""

from rest_framework import authentication, permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from apps.platform_config import services as config
from apps.rbac.services import has_perm
from apps.tenancy.context import activate, deactivate
from apps.tenancy.middleware import PLATFORM_PATHS, gate_blocks, gate_reason, resolve_membership
from apps.tenancy.models import Company


class TenantContextMixin:
    """For JWT clients the user is only known inside DRF, so the company is resolved here (TEN-02)."""

    def perform_authentication(self, request):
        """Runs before permission checks and throttles, so both see the resolved company."""
        super().perform_authentication(request)
        user = request.user
        django_request = request._request
        if isinstance(request.successful_authenticator, authentication.SessionAuthentication):
            company = django_request.company  # resolved and checked by TenantMiddleware
        else:  # Bearer token (app): resolve and check here
            membership = resolve_membership(user)
            company = membership.company if membership else None
            self._check_token_user(user, company)
            reason = gate_reason(user, company) if gate_blocks(request.path) else None
            if reason:
                code = "phone_verification_required" if reason == "phone" else f"company_{reason}"
                raise PermissionDenied({"code": code, "message": "Not available yet."})
        request.company = django_request.company = company
        staff_area = user.is_authenticated and user.is_staff and request.path.startswith(PLATFORM_PATHS)
        self._tenant_tokens = activate(company.id if company else None, bypass=staff_area)

    @staticmethod
    def _check_token_user(user, company):
        if not user.is_authenticated:
            return
        if company and company.status == Company.SUSPENDED:
            raise PermissionDenied({"code": "company_suspended", "message": "This company is suspended."})
        required = (
            config.get("security.staff_2fa_required")
            if user.is_staff
            else bool(company and (company.require_2fa or config.get("security.company_2fa_enforced")))
        )
        if required:
            from allauth.mfa.models import Authenticator

            if not Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists():
                raise PermissionDenied({"code": "mfa_required", "message": "Set up two-factor authentication."})

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        tokens = getattr(self, "_tenant_tokens", None)
        if tokens:
            deactivate(tokens)
            self._tenant_tokens = None
        return response


def perm(key):
    """Permission class requiring one RBAC permission (AUTH-11). Company permissions use the request's company."""

    class HasPermission(permissions.BasePermission):
        message = f"Missing permission: {key}"

        def has_permission(self, request, view):
            return has_perm(request.user, key, getattr(request, "company", None))

    HasPermission.__name__ = f"HasPermission[{key}]"
    return HasPermission


class AdminViewSet(TenantContextMixin, viewsets.ModelViewSet):
    """Super Admin API: platform staff only; read/write permission keys are set per viewset."""

    view_perm = None
    manage_perm = None

    def get_permissions(self):
        key = (
            self.view_perm if self.request.method in permissions.SAFE_METHODS else (self.manage_perm or self.view_perm)
        )
        return [permissions.IsAuthenticated(), perm(key)()]


def any_perm(*keys):
    """Permission class passing when the user has at least one of the keys."""

    class HasAnyPermission(permissions.BasePermission):
        message = f"Missing permission: one of {', '.join(keys)}"

        def has_permission(self, request, view):
            return any(has_perm(request.user, k, getattr(request, "company", None)) for k in keys)

    return HasAnyPermission
