"""WhatsApp webhook (SEC-13): /webhooks/whatsapp/<provider key>/

GET   Meta's subscription check: hub.verify_token must be our token for this provider → hub.challenge is echoed.
POST  messages and statuses, accepted only with a valid X-Hub-Signature-256 (app secret). Answered at once; each
      message is processed once (Meta retries).
"""

import hmac
import json
import logging

from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.providers.models import Provider

from . import cloud, services

log = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request, provider_key):
    provider = Provider.objects.filter(key=provider_key, capabilities__contains=["whatsapp"]).first()
    if not provider or provider.vendor not in cloud.ADAPTERS:
        return HttpResponseNotFound()
    if request.method == "GET":
        token = request.GET.get("hub.verify_token", "")
        if request.GET.get("hub.mode") == "subscribe" and hmac.compare_digest(token, services.webhook_token(provider)):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponseForbidden()
    body = request.body
    if not cloud.for_provider(provider).verify_signature(body, request.headers.get("X-Hub-Signature-256", "")):
        log.warning("WhatsApp webhook with a bad signature for %s", provider_key)
        return HttpResponseForbidden()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return HttpResponse(status=400)
    services.handle_webhook(provider, payload)
    return HttpResponse("ok")
