"""One error format for every API response (SDD-02 API Architecture)."""

from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    code = getattr(exc, "default_code", "error")
    message = getattr(exc, "detail", str(exc))
    details = {}
    if isinstance(data, dict) and {"code", "message"} <= set(data):
        code, message = data["code"], data["message"]
    elif isinstance(data, dict) and "detail" in data:
        message = data["detail"]
    else:
        details, message = data, "Invalid input."
    request = context.get("request")
    response.data = {
        "error": {
            "code": str(code),
            "message": str(message),
            "details": details,
            "request_id": getattr(getattr(request, "_request", None), "request_id", ""),
        }
    }
    return response
