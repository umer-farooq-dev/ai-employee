from django.core import signing
from django.db import connection
from django.http import FileResponse, Http404, JsonResponse

from apps.platform_config import services as config

from .storage import path_from_token, private_storage


def healthz(request):
    """Liveness / readiness check for any hosting (ENGR-05)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


def private_file(request, token):
    """Serve a private file only for a valid, unexpired signed token (TEN-03)."""
    try:
        path = path_from_token(token, max_age=config.get("security.signed_url_seconds"))
    except signing.BadSignature:
        raise Http404 from None
    if not private_storage.exists(path):
        raise Http404
    return FileResponse(private_storage.open(path, "rb"), as_attachment=False)
