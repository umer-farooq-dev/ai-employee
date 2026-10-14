"""Read and change platform settings. All code reads business values through get() — nothing is hard-coded."""

import ipaddress
import re

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import phone_validator

from .models import PlatformSetting
from .registry import BY_KEY, SETTINGS

CACHE_KEY = "platform_settings:v1"
RATE_RE = re.compile(r"^\d+/(second|minute|hour|day)$")


def get_all() -> dict:
    values = cache.get(CACHE_KEY)
    if values is None:
        values = {s.key: s.default for s in SETTINGS}
        values.update(dict(PlatformSetting.objects.values_list("key", "value")))
        cache.set(CACHE_KEY, values, None)
    return values


def get(key):
    if key not in BY_KEY:
        raise KeyError(f"Unknown setting {key!r}; add it to the registry first.")
    return get_all()[key]


def group(prefix: str) -> dict:
    """All values whose key starts with prefix, e.g. group('general.')."""
    return {k: v for k, v in get_all().items() if k.startswith(prefix)}


def clean(key, value):
    """Validate and normalise one value against its registry entry."""
    s = BY_KEY[key]
    if s.type == "boolean":
        return bool(value)
    if s.type == "number":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{s.label}: enter a whole number.") from None
        if (s.min is not None and value < s.min) or (s.max is not None and value > s.max):
            raise ValidationError(f"{s.label}: must be between {s.min} and {s.max}.")
        return value
    if s.type == "list":
        items = value if isinstance(value, list) else [v.strip() for v in str(value or "").splitlines()]
        items = [i for i in items if i]
        if key == "security.admin_ip_allowlist":
            for item in items:
                try:
                    ipaddress.ip_network(item, strict=False)
                except ValueError:
                    raise ValidationError(f"{s.label}: {item!r} is not a valid IP or CIDR range.") from None
        return items
    if s.type == "links":
        return [
            {"platform": str(i.get("platform", "")).strip(), "url": str(i.get("url", "")).strip()}
            for i in (value or [])
            if i.get("url")
        ]
    value = "" if value is None else str(value).strip()
    if s.type == "choice" and value not in {c[0] for c in s.choices}:
        raise ValidationError(f"{s.label}: invalid choice.")
    if s.type == "email" and value:
        validate_email(value)
    if s.type == "phone" and value:
        phone_validator(value)
    if s.type == "color" and value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValidationError(f"{s.label}: use a hex colour like #6534F4.")
    if key.startswith("security.api_rate") and not RATE_RE.match(value):
        raise ValidationError(f"{s.label}: use the format 100/hour.")
    return value


def update(values: dict, user=None, request=None) -> dict:
    """Validate, save and audit a set of changes. Returns {key: (old, new)} for changed keys."""
    current = get_all()
    cleaned = {k: clean(k, v) for k, v in values.items()}
    changed = {k: (current[k], v) for k, v in cleaned.items() if current[k] != v}
    if not changed:
        return {}
    with transaction.atomic():
        for key, (_old, new) in changed.items():
            PlatformSetting.objects.update_or_create(key=key, defaults={"value": new, "updated_by": user})
        from apps.audit.services import record

        record(
            request,
            "settings.update",
            "platform_setting",
            ",".join(changed),
            changes={k: {"old": o, "new": n} for k, (o, n) in changed.items()},
            user=user,
        )
    cache.delete(CACHE_KEY)
    return changed


def seed_missing():
    """Insert a row with the seed default for every registry key that has no row yet (idempotent)."""
    existing = set(PlatformSetting.objects.values_list("key", flat=True))
    PlatformSetting.objects.bulk_create(
        [PlatformSetting(key=s.key, value=s.default) for s in SETTINGS if s.key not in existing]
    )
    cache.delete(CACHE_KEY)
