"""AI providers (SA-09) and the LLM gateway (ENG-09). Super Admin views and the REST API both call these functions."""

import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.platform_config.services import get as setting

from .adapters import ProviderError, for_provider
from .models import CAPABILITIES, TASK_CAPABILITY, ModelRoute, Provider

EDITABLE = ["name", "description", "adapter", "base_url", "logo", "capabilities", "test_only", "sort_order"]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def production():
    return settings.ENVIRONMENT == "production"


def _adapter(provider):
    return for_provider(provider, timeout=setting("ai.request_timeout_seconds"))


def _clean_models(rows):
    """[{"id", "input_cost", "output_cost"}], ids unique, costs ≥ 0."""
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
        out.append({"id": model_id, **costs})
    return out


def _validate(provider):
    if provider.adapter not in dict(Provider.ADAPTERS):
        raise ValidationError("Unknown API type.")
    unknown = set(provider.capabilities) - {c for c, _ in CAPABILITIES}
    if unknown:
        raise ValidationError(f"Unknown capability: {', '.join(sorted(unknown))}.")
    url = urlparse(provider.base_url)
    if url.scheme not in ("https", "http") or not url.hostname:
        raise ValidationError("Base URL must be a full http(s) address.")
    if production() and url.scheme != "https":
        raise ValidationError("Base URL must use https in production.")
    if production() and provider.test_only and provider.is_active:
        raise ValidationError("Test-only providers cannot be switched on in production.")
    if provider.is_active and not provider.api_key and not (provider.test_only and url.hostname in LOCAL_HOSTS):
        raise ValidationError("Add the API key before switching this provider on.")


def save_provider(provider, data, user=None, request=None):
    """Create or update. api_key: blank keeps the stored key; remove_key=True deletes it. The key is never logged."""
    creating = provider is None
    provider = provider or Provider(key=data.get("key", ""))
    changes = {}
    for f in EDITABLE:
        if f in data and getattr(provider, f) != data[f]:
            changes[f] = {"old": getattr(provider, f), "new": data[f]}
            setattr(provider, f, data[f])
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
    """Calls the provider's model list (free, no tokens). Stores the result as health and returns the model ids."""
    try:
        if not provider.api_key and provider.adapter == "anthropic":
            raise ProviderError("No API key saved.")
        models = _adapter(provider).list_models()
        health = {"ok": True, "message": f"Connected · {len(models)} models available"}
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
        if model not in provider.model_ids:
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
