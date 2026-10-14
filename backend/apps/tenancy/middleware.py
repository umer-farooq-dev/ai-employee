from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect

from .context import activate, deactivate
from .models import Company, Membership

# Areas where platform staff work across companies (RLS bypass is set explicitly, never implied).
PLATFORM_PATHS = ("/superadmin/", "/api/v1/admin/")


def resolve_membership(user):
    """The signed-in user's active membership (one company per user in the MVP). Trusted source for the tenant."""
    if not user or not user.is_authenticated:
        return None
    tokens = activate(None, bypass=True)  # the lookup itself is a platform read
    try:
        return (
            Membership.all_companies.select_related("company", "role")
            .filter(user=user, status=Membership.ACTIVE, company__deleted_at__isnull=True)
            .order_by("created_at")
            .first()
        )
    finally:
        deactivate(tokens)


class TenantMiddleware:
    """Resolves request.company from the signed-in user's membership and activates the tenant context (TEN-01/02)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        request.membership = resolve_membership(user)
        request.company = request.membership.company if request.membership else None

        if (
            request.company
            and request.company.status == Company.SUSPENDED
            and not getattr(request, "impersonator", None)
        ):
            return self._suspended(request)

        staff_area = user.is_authenticated and user.is_staff and request.path.startswith(PLATFORM_PATHS)
        tokens = activate(request.company.id if request.company else None, bypass=staff_area)
        try:
            return self.get_response(request)
        finally:
            deactivate(tokens)

    @staticmethod
    def _suspended(request):
        """TEN-06: users of a suspended company cannot use the platform."""
        logout(request)
        if request.path.startswith("/api/"):
            return JsonResponse(
                {"error": {"code": "company_suspended", "message": "This company is suspended."}}, status=403
            )
        messages.error(request, "Your company account is suspended. Please contact support.")
        return redirect("account_login")
