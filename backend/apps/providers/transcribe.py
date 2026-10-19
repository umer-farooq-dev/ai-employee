"""Speech-to-text for recorded audio (WA-09 WhatsApp voice notes). Live calls stream through the Voice Gateway; a voice
note is one short file, so it goes to the same speech-to-text routes of its language (Super Admin → Languages &
Voices) over each vendor's file API, with the same failover order.

Vendors without a file API here are skipped (the next route is tried).
"""

import logging

from apps.platform_config.services import get as setting

from . import services
from .adapters import ProviderError, multipart, request_raw

log = logging.getLogger(__name__)


def _model(route, default=""):
    return route.model or default


def _openai(route, audio, mime, language, timeout):
    p = route.provider
    body, ctype = multipart(
        {"model": _model(route, "whisper-1"), "language": language},
        {"file": ("voice.ogg", audio, mime)},
    )
    headers = {"Authorization": f"Bearer {p.api_key}", "Content-Type": ctype}
    data, _ = request_raw("POST", f"{p.base_url.rstrip('/')}/audio/transcriptions", headers, body, timeout)
    return data.get("text", "")


def _deepgram(route, audio, mime, language, timeout):
    p = route.provider
    query = f"model={_model(route, 'nova-2')}&language={route.language.locale or language}&smart_format=true"
    headers = {"Authorization": f"Token {p.api_key}", "Content-Type": mime}
    data, _ = request_raw("POST", f"{p.base_url.rstrip('/')}/v1/listen?{query}", headers, audio, timeout)
    alts = (((data.get("results") or {}).get("channels") or [{}])[0].get("alternatives")) or [{}]
    return alts[0].get("transcript", "")


def _sarvam(route, audio, mime, language, timeout):
    p = route.provider
    fields = {"language_code": route.language.locale or language}
    if route.model:
        fields["model"] = route.model
    body, ctype = multipart(fields, {"file": ("voice.ogg", audio, mime)})
    headers = {"api-subscription-key": p.api_key, "Content-Type": ctype}
    data, _ = request_raw("POST", f"{p.base_url.rstrip('/')}/speech-to-text", headers, body, timeout)
    return data.get("transcript", "")


def _elevenlabs(route, audio, mime, language, timeout):
    p = route.provider
    body, ctype = multipart(
        {"model_id": _model(route, "scribe_v1"), "language_code": language}, {"file": ("voice.ogg", audio, mime)}
    )
    headers = {"xi-api-key": p.api_key, "Content-Type": ctype}
    data, _ = request_raw("POST", f"{p.base_url.rstrip('/')}/v1/speech-to-text", headers, body, timeout)
    return data.get("text", "")


_local_models = {}


def _whisper_local(route, audio, mime, language, timeout):
    """Free local testing: faster-whisper (installed with requirements/voice-local.txt)."""
    import io

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ProviderError("Whisper (local) is not installed (requirements/voice-local.txt).") from None
    name = _model(route, "small")
    if name not in _local_models:
        _local_models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    segments, _ = _local_models[name].transcribe(io.BytesIO(audio), language=language or None)
    return " ".join(s.text.strip() for s in segments)


FILE_APIS = {
    "openai": _openai,
    "deepgram": _deepgram,
    "sarvam": _sarvam,
    "elevenlabs": _elevenlabs,
    "whisper_local": _whisper_local,
}


def transcribe(audio, mime, language):
    """→ (text, provider key). Raises ProviderError when no route of the language could transcribe it."""
    timeout = setting("ai.request_timeout_seconds")
    errors = []
    for route in services.speech_chain(language, "stt"):
        fn = FILE_APIS.get(route.provider.vendor)
        if not fn:
            errors.append(f"{route.provider.name}: no file transcription")
            continue
        try:
            text = (fn(route, audio, mime, language, timeout) or "").strip()
        except ProviderError as exc:
            log.warning("voice note transcription failed on %s: %s", route.provider.key, exc)
            errors.append(f"{route.provider.name}: {exc}")
            continue
        if text:
            return text, route.provider.key
    raise ProviderError("; ".join(errors) or f"No speech-to-text route for {language}.")
