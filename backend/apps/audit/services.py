from apps.core.request import client_ip, current_request

from .models import AuditLog


def record(request, action, entity_type="", entity_id="", changes=None, user=None, company=None, category="general"):
    """Write one audit entry. `request` may be None (falls back to the current request, if any)."""
    request = request or current_request()
    user = user or (getattr(request, "user", None) if request else None)
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None
    impersonator = getattr(request, "impersonator", None) if request else None
    return AuditLog.objects.create(
        company=company,
        actor=user,
        actor_email=getattr(user, "email", "") or "",
        impersonator_email=getattr(impersonator, "email", "") or "",
        category=category,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        changes=changes or {},
        ip=client_ip(request) if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        request_id=getattr(request, "request_id", "") if request else "",
    )
