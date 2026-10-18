"""Builds Pipecat speech services from the routes set in Super Admin → Languages & Voices (VOICE-08, 21).

A route is plain data (vendor, key, model, voice, locale, params). Each vendor maps to a Pipecat service class; the
model / language / voice go into the service's Settings, extra route parameters too. Several routes become one
ServiceSwitcher with the failover strategy, so the next provider takes over when one fails mid-call.
"""

import dataclasses
import importlib
import inspect
import json

from loguru import logger

STT = {
    "sarvam": ("pipecat.services.sarvam.stt", "SarvamSTTService"),
    "deepgram": ("pipecat.services.deepgram.stt", "DeepgramSTTService"),
    "elevenlabs": ("pipecat.services.elevenlabs.stt", "ElevenLabsRealtimeSTTService"),
    "openai": ("pipecat.services.openai.stt", "OpenAISTTService"),
    "azure": ("pipecat.services.azure.stt", "AzureSTTService"),
    "google": ("pipecat.services.google.stt", "GoogleSTTService"),
    "whisper_local": ("pipecat.services.whisper.stt", "WhisperSTTService"),
}
TTS = {
    "sarvam": ("pipecat.services.sarvam.tts", "SarvamTTSService"),
    "deepgram": ("pipecat.services.deepgram.tts", "DeepgramTTSService"),
    "elevenlabs": ("pipecat.services.elevenlabs.tts", "ElevenLabsTTSService"),
    "cartesia": ("pipecat.services.cartesia.tts", "CartesiaTTSService"),
    "openai": ("pipecat.services.openai.tts", "OpenAITTSService"),
    "azure": ("pipecat.services.azure.tts", "AzureTTSService"),
    "google": ("pipecat.services.google.tts", "GoogleTTSService"),
    "kokoro_local": ("pipecat.services.kokoro.tts", "KokoroTTSService"),
}


class SpeechUnavailable(Exception):
    pass


def _language(locale):
    from pipecat.transcriptions.language import Language

    for value in (locale, locale.split("-")[0]):
        try:
            return Language(value)
        except ValueError:
            continue
    return locale


def _class(table, vendor):
    if vendor not in table:
        raise SpeechUnavailable(f"No voice pipeline for vendor {vendor!r}.")
    module, name = table[vendor]
    try:
        return getattr(importlib.import_module(module), name)
    except ImportError as exc:
        raise SpeechUnavailable(f"{vendor}: install the Pipecat extra for it on the Voice Gateway ({exc}).") from None


def _settings(cls, route, kind):
    settings_cls = getattr(cls, "Settings", None)
    if settings_cls is None:
        return None
    names = {f.name for f in dataclasses.fields(settings_cls)}
    values = {"language": _language(route["locale"])}
    if route.get("model") and route["model"] != "default":
        values["model"] = route["model"]
    if kind == "tts" and route.get("voice"):
        values["voice"] = route["voice"]
    if kind == "tts" and route.get("speed") and route["speed"] != 1.0 and "speed" in names:
        values["speed"] = route["speed"]
    extra = {}
    for key, value in (route.get("params") or {}).items():
        (values if key in names else extra)[key] = value
    values = {k: v for k, v in values.items() if k in names}
    if extra and "extra" in names:
        values["extra"] = extra
    return settings_cls(**values)


def _kwargs(cls, route, session):
    """Credentials and connection details, only those this service class accepts."""
    accepted = set(inspect.signature(cls.__init__).parameters)
    cfg = route.get("config") or {}
    candidates = {
        "api_key": route.get("api_key") or None,
        "region": cfg.get("region"),
        "aiohttp_session": session,
    }
    if route["vendor"] == "google":
        candidates["credentials"] = route.get("api_key")
        candidates.pop("api_key")
    if route["vendor"] == "kokoro_local":
        candidates.pop("api_key")
    return {k: v for k, v in candidates.items() if k in accepted and v is not None}


def build(kind, route, http_session):
    cls = _class(STT if kind == "stt" else TTS, route["vendor"])
    kwargs = _kwargs(cls, route, http_session)
    settings = _settings(cls, route, kind)
    if settings is not None and "settings" in inspect.signature(cls.__init__).parameters:
        kwargs["settings"] = settings
    service = cls(**kwargs)
    logger.info(f"voice: {kind} {route['provider']} / {route.get('model')} ({route['locale']})")
    return service


def chain(kind, routes, http_session):
    """[routes] → one service, or a failover ServiceSwitcher when there are several (unusable routes skipped)."""
    from pipecat.pipeline.service_switcher import ServiceSwitcher, ServiceSwitcherStrategyFailover

    services, errors = [], []
    for route in routes:
        try:
            services.append(build(kind, route, http_session))
        except (SpeechUnavailable, Exception) as exc:  # noqa: BLE001 — a broken route must not stop the call
            errors.append(f"{route['provider']}: {exc}")
            logger.warning(f"voice: {kind} route skipped — {exc}")
    if not services:
        raise SpeechUnavailable("; ".join(errors) or f"No {kind} provider is set for this language.")
    if len(services) == 1:
        return services[0], errors
    return ServiceSwitcher(services=services, strategy_type=ServiceSwitcherStrategyFailover), errors


def describe(routes):
    return json.dumps([f"{r['provider']}/{r.get('model')}" for r in routes])
