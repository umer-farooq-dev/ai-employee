"""Razorpay webhook (SEC-13): /webhooks/razorpay/ — accepted only with a valid X-Razorpay-Signature (webhook secret).
Renewals, failed payments, cancellations and paid orders update the subscription (apps.billing.services.webhook)."""

import logging

from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.providers.adapters import ProviderError

from . import services

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    try:
        result = services.webhook(request.body.decode("utf-8"), request.headers.get("X-Razorpay-Signature", ""))
    except ProviderError as exc:
        log.warning("Razorpay webhook refused: %s", exc)
        return HttpResponseForbidden()
    except ValueError:
        return HttpResponse(status=400)
    return HttpResponse(result)
