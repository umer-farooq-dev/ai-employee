"""Telephony webhooks (SEC-13): /webhooks/telephony/<provider key>/<token>/<action>/

- answer   provider asks what to do with an answered / incoming call → stream audio to the Voice Gateway
- status   call status changes (ringing, answered, completed, busy, no answer …)

Each request must carry our per-provider token in the URL and, where the vendor signs callbacks, a valid signature.
Status callbacks are de-duplicated (providers retry).
"""

import hmac
import logging
from xml.sax.saxutils import escape

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.platform_config.services import get as setting
from apps.providers.models import Provider
from apps.tenancy.context import company_context, platform_context

from . import handoff, services, telephony
from .models import Call, WebhookEvent

log = logging.getLogger(__name__)


def _verified(request, provider_key, token):
    """→ (provider, adapter, params) or an HttpResponse to return."""
    provider = Provider.objects.filter(key=provider_key, capabilities__contains=["telephony"]).first()
    if not provider or provider.vendor not in telephony.ADAPTERS:
        return HttpResponseNotFound()
    if not hmac.compare_digest(token, services.webhook_token(provider)):
        return HttpResponseForbidden()
    adapter = telephony.for_provider(provider)
    params = {**request.GET.dict(), **request.POST.dict()} if request.method == "POST" else request.GET.dict()
    signed = request.POST.dict() if request.method == "POST" else {}
    url = settings.PUBLIC_BASE_URL + request.get_full_path()  # the address the provider signed (behind a proxy too)
    if provider.api_key and not adapter.verify(url, signed, request.headers):
        log.warning("telephony webhook signature mismatch for %s", provider_key)
        return HttpResponseForbidden()
    return provider, adapter, params


def _xml(adapter, body):
    return HttpResponse(body, content_type=adapter.content_type)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def answer(request, provider_key, token):
    checked = _verified(request, provider_key, token)
    if isinstance(checked, HttpResponse):
        return checked
    provider, adapter, params = checked
    event = adapter.parse(params)
    call = services.find_call(provider, event, params.get("call")) if params.get("call") else None
    if call is None:
        call = services.inbound(provider, event)
        if call is None:
            return _xml(adapter, adapter.hangup_xml())
    with platform_context():
        Call.all_companies.filter(pk=call.pk).update(provider_call_id=call.provider_call_id or event.get("call_id", ""))
    mode = "talk"
    if call.direction == "outbound" and event.get("answered_by") == "machine":
        services.apply_event(call, {"answered_by": "machine"})
        if setting("calling.voicemail_action") == "hangup":
            return _xml(adapter, adapter.hangup_xml())
        mode = "voicemail"
    return _xml(adapter, adapter.answer(services.stream_url(call), services.stream_params(call, mode)))


def _handoff(params):
    from .models import Handoff

    with platform_context():
        return (
            Handoff.all_companies.select_related("call__provider", "assigned_user", "conversation__employee")
            .filter(pk=services._uuid(str(params.get("handoff") or "")))
            .first()
        )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def transfer(request, provider_key, token):
    """VOICE-11: dial instructions for the agent the handoff is ringing (warm: whisper first)."""
    checked = _verified(request, provider_key, token)
    if isinstance(checked, HttpResponse):
        return checked
    _provider, adapter, params = checked
    h = _handoff(params)
    if h is None:
        return _xml(adapter, adapter.hangup_xml())
    with company_context(h.company_id):
        return _xml(adapter, handoff.dial_response(h))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whisper(request, provider_key, token):
    """HO-03 warm transfer: the agent hears the summary before the caller is connected."""
    checked = _verified(request, provider_key, token)
    if isinstance(checked, HttpResponse):
        return checked
    _provider, adapter, params = checked
    h = _handoff(params)
    if h is None:
        return _xml(adapter, "<Response/>")
    with company_context(h.company_id):
        handoff.answered(h)  # the agent picked up
    say = "Say" if h.call.provider.vendor == "twilio" else "Speak"
    return _xml(adapter, f"<Response><{say}>{escape(h.summary)}</{say}></Response>")


def recording(request, token):
    """VOICE-12 / REC-03: a signed, short-lived link made after the permission check (and audited) plays or
    downloads the decrypted recording."""
    from django.core import signing
    from django.http import Http404

    from apps.core.crypto import decrypt_bytes
    from apps.core.storage import private_storage

    try:
        data = signing.loads(token, salt=services.RECORDING_SALT, max_age=setting("security.signed_url_seconds"))
    except signing.BadSignature:
        raise Http404 from None
    with platform_context():
        call = Call.all_companies.filter(pk=services._uuid(data.get("c", ""))).first()
    if call is None or call.recording_status != "stored" or not private_storage.exists(call.recording_key):
        raise Http404
    with private_storage.open(call.recording_key, "rb") as fh:
        audio = decrypt_bytes(fh.read())
    response = HttpResponse(audio, content_type="audio/wav")
    disposition = "attachment" if data.get("d") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="call-{call.pk}.wav"'
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["GET", "POST"])
def transfer_result(request, provider_key, token):
    """The agent's leg ended: answered → done; busy / no answer → next agent or the no-agent message."""
    checked = _verified(request, provider_key, token)
    if isinstance(checked, HttpResponse):
        return checked
    _provider, adapter, params = checked
    h = _handoff(params)
    if h is None:
        return _xml(adapter, adapter.hangup_xml())
    outcome = str(params.get("DialCallStatus") or params.get("DialStatus") or "").lower()
    with company_context(h.company_id):
        if outcome in ("completed", "answered") and h.accepted_at:
            handoff.finish(h)
            return _xml(adapter, adapter.hangup_xml())
        h = handoff.missed(h)
        return _xml(adapter, handoff.dial_response(h))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def status(request, provider_key, token):
    checked = _verified(request, provider_key, token)
    if isinstance(checked, HttpResponse):
        return checked
    provider, adapter, params = checked
    event = adapter.parse(params)
    try:
        with transaction.atomic():
            WebhookEvent.objects.create(provider_key=provider.key, event_key=event["event_id"][:200], payload=params)
    except IntegrityError:
        return HttpResponse(status=204)  # already handled (provider retry)
    call = services.find_call(provider, event, params.get("call"))
    if call is not None:
        services.apply_event(call, event)
    return HttpResponse(status=204)
