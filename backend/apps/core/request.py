"""Request-scoped helpers: request id, client IP and access to the current request from services."""

import time
import uuid
from contextvars import ContextVar

_current_request: ContextVar = ContextVar("current_request", default=None)


def current_request():
    return _current_request.get()


def client_ip(request):
    # Behind a reverse proxy the proxy must set X-Forwarded-For; the first address is the client.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


class RequestContextMiddleware:
    """Adds request.request_id (also returned as X-Request-ID) and logs /api/ calls (SA-17 API log)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex
        token = _current_request.set(request)
        start = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            _current_request.reset(token)
        response["X-Request-ID"] = request.request_id
        if request.path.startswith(("/api/", "/public/")):
            self._log_api(request, response, start)
        return response

    @staticmethod
    def _log_api(request, response, start):
        from apps.audit.models import ApiRequestLog

        user = getattr(request, "user", None)
        company = getattr(request, "company", None)
        ApiRequestLog.objects.create(
            method=request.method,
            path=request.path[:500],
            status=response.status_code,
            duration_ms=int((time.monotonic() - start) * 1000),
            user_email=getattr(user, "email", "") if getattr(user, "is_authenticated", False) else "",
            company_id=getattr(company, "id", None),
            ip=client_ip(request),
            request_id=request.request_id,
        )
