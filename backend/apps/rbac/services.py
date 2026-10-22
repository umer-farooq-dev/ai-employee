from django.core.exceptions import PermissionDenied, ValidationError

from .catalog import PERMISSIONS


def has_perm(user, key, company=None) -> bool:
    """Single permission check used by every screen and every API (AUTH-11 / SEC-03)."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    scope = PERMISSIONS[key][0]
    if scope == "company" and company is not None:
        from apps.billing.access import perm_allowed

        if not perm_allowed(company, key):  # SA-20: the plan does not include this feature
            return False
    if user.is_superuser:
        return True
    if scope == "platform":
        return bool(user.is_staff and user.platform_role_id and key in user.platform_role.permissions)
    from apps.tenancy.models import Membership

    membership = (
        Membership.all_companies.select_related("role")
        .filter(user=user, company=company, status=Membership.ACTIVE)
        .first()
        if company
        else None
    )
    return bool(membership and key in membership.role.permissions)


def require(user, key, company=None):
    if not has_perm(user, key, company):
        raise PermissionDenied(f"Missing permission: {key}")


def clean_permissions(scope, keys):
    unknown = [k for k in keys if k not in PERMISSIONS or PERMISSIONS[k][0] != scope]
    if unknown:
        raise ValidationError(f"Unknown permissions for {scope} roles: {', '.join(unknown)}")
    return sorted(set(keys))
