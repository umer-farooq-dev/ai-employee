"""AI, speech and telephony providers (SA-09, SA-10), the LLM gateway (ENG-09), languages, voices and speech routes
(SA-11). Super Admin views and the REST API both call these functions."""

import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.platform_config.services import get as setting

from . import vendors
from .adapters import ProviderError, for_provider
from .models import (
    CAPABILITIES,
    LANGUAGE_TEXTS,
    LLM_CAPABILITIES,
    TASK_CAPABILITY,
    Language,
    ModelRoute,
    Provider,
    SpeechRoute,
    Voice,
)

EDITABLE = [
    "name",
    "description",
    "adapter",
    "vendor",
    "base_url",
    "logo",
    "capabilities",
    "test_only",
    "sort_order",
]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def production():
    return settings.ENVIRONMENT == "production"


def _adapter(provider):
    return for_provider(provider, timeout=setting("ai.request_timeout_seconds"))


def _clean_models(rows):
    """[{"id", "input_cost", "output_cost"[, "kind"]}], ids unique, costs ≥ 0; kind = stt / tts for speech models."""
    out, seen = [], set()
    for row in rows or []:
        row = row if isinstance(row, dict) else {"id": row}
        model_id = str(row.get("id", "")).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        try:
            costs = {k: max(float(row.get(k) or 0), 0.0) for k in ("input_cost", "output_cost")}
        except (TypeError, ValueError):
            raise ValidationError(f"{model_id}: prices must be numbers.") from None
        kind = {"kind": row["kind"]} if row.get("kind") in ("stt", "tts") else {}
        out.append({"id": model_id, **costs, **kind})
    return out


def _validate(provider):
    if provider.adapter not in dict(Provider.ADAPTERS):
        raise ValidationError("Unknown API type.")
    unknown = set(provider.capabilities) - {c for c, _ in CAPABILITIES}
    if unknown:
        raise ValidationError(f"Unknown capability: {', '.join(sorted(unknown))}.")
    if provider.vendor and provider.vendor not in vendors.VENDORS:
        raise ValidationError("Unknown speech / telephony vendor.")
    voice_caps = set(provider.capabilities) - {c for c, _ in LLM_CAPABILITIES}
    if voice_caps and not provider.vendor:
        raise ValidationError("Choose the vendor for speech / telephony capabilities.")
    url = urlparse(provider.base_url)
    if url.scheme not in ("https", "http") or not url.hostname:
        raise ValidationError("Base URL must be a full http(s) address.")
    local = provider.test_only and url.hostname in LOCAL_HOSTS
    if production() and url.scheme != "https" and not local:
        raise ValidationError("Base URL must use https in production.")
    if production() and provider.test_only and provider.is_active:
        raise ValidationError("Test-only providers cannot be switched on in production.")
    if provider.is_active and not provider.api_key and not local and vendors.needs_key(provider):
        label = (vendors.spec(provider) or {}).get("secret") or "API key"
        raise ValidationError(f"Add the {label} before switching this provider on.")
    if provider.is_active and vendors.missing_config(provider):
        raise ValidationError(f"Fill in {', '.join(vendors.missing_config(provider))} before switching on.")


def save_provider(provider, data, user=None, request=None):
    """Create or update. api_key: blank keeps the stored key; remove_key=True deletes it. The key is never logged."""
    creating = provider is None
    provider = provider or Provider(key=data.get("key", ""))
    changes = {}
    for f in EDITABLE:
        if f in data and getattr(provider, f) != data[f]:
            changes[f] = {"old": getattr(provider, f), "new": data[f]}
            setattr(provider, f, data[f])
    if "config" in data:
        cfg = data["config"] if isinstance(data["config"], dict) else {}
        known = {name for name, *_ in (vendors.VENDORS.get(provider.vendor) or {"config": []})["config"]}
        cfg = {str(k): str(v).strip() for k, v in cfg.items() if k in known and str(v).strip()}
        if cfg != provider.config:
            changes["config"] = {"old": provider.config, "new": cfg}  # identifiers only, never secrets
            provider.config = cfg
    if "available_models" in data:
        cleaned = _clean_models(data["available_models"])
        if cleaned != provider.available_models:
            changes["available_models"] = {"old": provider.model_ids, "new": [m["id"] for m in cleaned]}
            provider.available_models = cleaned
    if data.get("remove_key"):
        provider.api_key = ""
        provider.is_active = False
        changes["api_key"] = "removed"
    elif data.get("api_key"):
        provider.api_key = data["api_key"].strip()
        changes["api_key"] = "replaced"
    if "api_key" in changes:
        provider.health = {}
    _validate(provider)
    provider.full_clean(exclude=["api_key"])
    provider.save()
    if changes or creating:
        record(
            request,
            "ai_provider.create" if creating else "ai_provider.update",
            "provider",
            provider.key,
            changes=changes,
            user=user,
        )
    return provider


def set_active(provider, active, user=None, request=None):
    provider.is_active = bool(active)
    _validate(provider)
    provider.save(update_fields=["is_active", "updated_at"])
    record(request, "ai_provider.on" if active else "ai_provider.off", "provider", provider.key, user=user)
    return provider


def delete_provider(provider, user=None, request=None):
    record(request, "ai_provider.delete", "provider", provider.key, user=user)
    provider.delete()


def test_connection(provider):
    """A free call to the provider (model list, account or voice list). Stores the result as health and returns the
    LLM model ids (empty for speech / telephony vendors)."""
    try:
        if provider.vendor and not set(provider.capabilities) & {c for c, _ in LLM_CAPABILITIES}:
            models, message = [], vendors.test(provider, timeout=setting("ai.request_timeout_seconds"))
        else:
            if not provider.api_key and provider.adapter == "anthropic":
                raise ProviderError("No API key saved.")
            models = _adapter(provider).list_models()
            message = f"Connected · {len(models)} models available"
        health = {"ok": True, "message": message}
    except ProviderError as exc:
        models, health = [], {"ok": False, "message": str(exc)}
    provider.health = {**health, "checked_at": timezone.now().isoformat()}
    provider.save(update_fields=["health", "updated_at"])
    return health, models


# ------------------------------------------------------------------ model per task (fallback order)
def routes():
    return {task: list(ModelRoute.objects.filter(task=task).select_related("provider")) for task in TASK_CAPABILITY}


def save_routes(task, rows, user=None, request=None):
    """Replace the fallback chain for one task. rows: [{"provider": id/key, "model": str, "params": {}}] in order."""
    if task not in TASK_CAPABILITY:
        raise ValidationError("Unknown task.")
    need = TASK_CAPABILITY[task]
    cleaned = []
    for i, row in enumerate(rows, start=1):
        ref = str(row.get("provider", ""))
        provider = Provider.objects.filter(key=ref).first() or Provider.objects.filter(pk=_uuid(ref)).first()
        if not provider:
            raise ValidationError(f"Row {i}: choose a provider.")
        if need not in provider.capabilities:
            raise ValidationError(f"Row {i}: {provider.name} does not offer {dict(CAPABILITIES)[need].lower()}.")
        model = str(row.get("model", "")).strip()
        if model not in [m["id"] for m in provider.available_models if not m.get("kind")]:  # speech models excluded
            raise ValidationError(f"Row {i}: add the model {model or '(empty)'} to {provider.name} first.")
        params = row.get("params") or {}
        if not isinstance(params, dict):
            raise ValidationError(f"Row {i}: parameters must be a JSON object.")
        cleaned.append(ModelRoute(task=task, provider=provider, model=model, params=params, priority=i))
    with transaction.atomic():
        old = [f"{r.provider.key}/{r.model}" for r in ModelRoute.objects.filter(task=task).select_related("provider")]
        ModelRoute.objects.filter(task=task).delete()
        ModelRoute.objects.bulk_create(cleaned)
        record(
            request,
            "ai_route.update",
            "model_route",
            task,
            changes={"old": old, "new": [f"{r.provider.key}/{r.model}" for r in cleaned]},
            user=user,
        )
    return cleaned


def _uuid(value):
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ------------------------------------------------------------------ gateway
class NoProviderAvailable(Exception):
    pass


def _chain(task):
    usable = []
    for route in ModelRoute.objects.filter(task=task, provider__is_active=True).select_related("provider"):
        if production() and route.provider.test_only:
            continue  # FreeLLMAPI etc. never serve production traffic (D23)
        usable.append(route)
    return usable


def has_route(task):
    return bool(_chain(task))


def _call(task, fn):
    errors = []
    for route in _chain(task):
        try:
            result = fn(_adapter(route.provider), route)
        except ProviderError as exc:
            errors.append(f"{route.provider.name} / {route.model}: {exc}")
            continue  # fallback to the next provider in priority order
        return {**result, "provider": route.provider.key, "route_model": route.model, "fallback_errors": errors}
    raise NoProviderAvailable("; ".join(errors) or f"No active provider is set for {task}.")


def chat(task, messages, tools=None, **params):
    """Run one LLM call for `task` through its routes (priority order, automatic fallback)."""
    return _call(task, lambda a, r: a.chat(r.model, messages, tools=tools, **{**r.params, **params}))


def embed(texts):
    return _call("embedding", lambda a, r: a.embed(r.model, texts))


# ------------------------------------------------------------------ SA-11 languages, voices, speech routes
LANGUAGE_FIELDS = ["code", "name", "native_name", "locale", "script", "is_active", "sort_order"]
TEXT_KEYS = {k for k, _ in LANGUAGE_TEXTS}


def save_language(language, data, user=None, request=None):
    creating = language is None
    language = language or Language()
    changes = {}
    for f in LANGUAGE_FIELDS:
        if f in data and getattr(language, f) != data[f]:
            if f == "code" and not creating:
                raise ValidationError("The language code cannot be changed.")
            changes[f] = {"old": getattr(language, f), "new": data[f]}
            setattr(language, f, data[f])
    if "texts" in data:
        texts = {}
        for key, value in (data["texts"] or {}).items():
            if key not in TEXT_KEYS:
                raise ValidationError(f"Unknown text: {key}.")
            value = [v.strip() for v in value if str(v).strip()] if key == "fillers" else str(value or "").strip()
            if value:
                texts[key] = value
        if texts != language.texts:
            changes["texts"] = sorted(set(texts) | set(language.texts))
            language.texts = texts
    if not language.is_active and Language.objects.exclude(pk=language.pk).filter(is_active=True).count() == 0:
        raise ValidationError("At least one language must stay switched on.")
    language.full_clean()
    language.save()
    if changes or creating:
        record(request, "language.create" if creating else "language.update", "language", language.code, changes, user)
    return language


def delete_language(language, user=None, request=None):
    from apps.agents.models import AIEmployee
    from apps.tenancy.context import platform_context

    with platform_context():
        used = AIEmployee.all_companies.filter(languages__contains=[language.code]).exists()
    if used:
        raise ValidationError("AI Employees speak this language — switch it off instead of deleting it.")
    record(request, "language.delete", "language", language.code, user=user)
    language.delete()


def save_voice(voice, data, user=None, request=None):
    creating = voice is None
    voice = voice or Voice()
    for f in ("name", "gender", "style", "sample", "provider_voice_id", "is_active", "sort_order"):
        if f in data:
            setattr(voice, f, data[f])
    if "language" in data:
        voice.language = _language(data["language"])
    if "provider" in data:
        voice.provider = _provider(data["provider"], "tts")
    voice.full_clean()
    voice.save()
    record(
        request,
        "voice.create" if creating else "voice.update",
        "voice",
        str(voice.pk),
        {"name": voice.name, "language": voice.language.code, "provider": voice.provider.key},
        user,
    )
    return voice


def delete_voice(voice, user=None, request=None):
    record(request, "voice.delete", "voice", str(voice.pk), {"name": voice.name}, user)
    voice.delete()


def _language(ref):
    lang = Language.objects.filter(code=str(ref)).first() or Language.objects.filter(pk=_uuid(str(ref))).first()
    if not lang:
        raise ValidationError("Choose a language.")
    return lang


def _provider(ref, capability):
    ref = str(ref or "")
    provider = Provider.objects.filter(key=ref).first() or Provider.objects.filter(pk=_uuid(ref)).first()
    if not provider:
        raise ValidationError("Choose a provider.")
    if capability not in provider.capabilities:
        raise ValidationError(f"{provider.name} does not offer {dict(CAPABILITIES)[capability].lower()}.")
    return provider


def save_speech_routes(language, kind, rows, user=None, request=None):
    """Replace the speech-to-text or text-to-speech chain of a language. rows: [{"provider", "model", "voice",
    "params"}] in priority order — row 1 is used, the next rows take over when a provider fails (VOICE-21)."""
    if kind not in dict(SpeechRoute.KINDS):
        raise ValidationError("Unknown route kind.")
    cleaned = []
    for i, row in enumerate(rows, start=1):
        try:
            provider = _provider(row.get("provider"), kind)
        except ValidationError as exc:
            raise ValidationError(f"Row {i}: {exc.messages[0]}") from None
        model = str(row.get("model", "")).strip()
        usable = [m["id"] for m in provider.available_models if m.get("kind", kind) == kind]
        if provider.available_models and model not in usable:
            label = dict(SpeechRoute.KINDS)[kind].lower()
            raise ValidationError(f"Row {i}: add the {label} model {model or '(empty)'} to {provider.name} first.")
        voice = None
        if kind == "tts":
            voice = Voice.objects.filter(pk=_uuid(str(row.get("voice") or "")), provider=provider).first()
            if not voice:
                raise ValidationError(f"Row {i}: choose a {provider.name} voice for {language.name}.")
        params = row.get("params") or {}
        if not isinstance(params, dict):
            raise ValidationError(f"Row {i}: parameters must be a JSON object.")
        cleaned.append(
            SpeechRoute(language=language, kind=kind, provider=provider, model=model, voice=voice, params=params)
        )
        cleaned[-1].priority = i
    with transaction.atomic():
        old = [str(r) for r in SpeechRoute.objects.filter(language=language, kind=kind).select_related("provider")]
        SpeechRoute.objects.filter(language=language, kind=kind).delete()
        SpeechRoute.objects.bulk_create(cleaned)
        record(
            request,
            "speech_route.update",
            "language",
            language.code,
            {"kind": kind, "old": old, "new": [f"{r.provider.key}/{r.model}" for r in cleaned]},
            user,
        )
    return cleaned


def speech_chain(language_code, kind):
    """Usable routes for a language in failover order (switched-off and, in production, test-only skipped)."""
    usable = []
    qs = SpeechRoute.objects.filter(language__code=language_code, kind=kind, provider__is_active=True)
    for route in qs.select_related("provider", "voice"):
        if production() and route.provider.test_only:
            continue
        usable.append(route)
    return usable


def provider_voices(provider, locale=""):
    """Voices offered by the vendor (for the catalogue import)."""
    try:
        return vendors.voices(provider, locale, timeout=setting("ai.request_timeout_seconds"))
    except ProviderError as exc:
        raise ValidationError(str(exc)) from None
