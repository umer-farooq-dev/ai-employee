"""ENGR-05: platform alerts for the operations team, checked every 5 minutes by the scheduler (ops_watch).

Alerts: a burst of server errors, a switched-on provider failing its connection test, and the scheduler itself not
running (seen by /healthz/ from an external uptime monitor). Each alert is e-mailed once per cool-down. Thresholds and
recipients: Super Admin → System Settings → Monitoring & alerts.
"""

import time
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.platform_config import services as config

from .models import ErrorLog

HEARTBEAT = "scheduler:heartbeat"
HEARTBEAT_STALE = 300  # seconds


def beat():
    cache.set(HEARTBEAT, time.time(), None)


def scheduler_ok():
    last = cache.get(HEARTBEAT)
    return last is not None and time.time() - last < HEARTBEAT_STALE


def problems(now=None):
    """[(alert key, title, details)] for everything wrong right now."""
    from apps.providers.models import Provider

    now = now or timezone.now()
    window = config.get("monitoring.window_minutes")
    found = []
    errors = ErrorLog.objects.filter(created_at__gte=now - timedelta(minutes=window))
    count = errors.count()
    if count >= config.get("monitoring.error_threshold"):
        latest = "\n".join(f"{e.created_at:%H:%M} {e.path or e.logger}: {e.message[:200]}" for e in errors[:5])
        found.append(("errors", f"{count} server errors in {window} minutes", latest))
    for p in Provider.objects.filter(is_active=True).exclude(health={}):
        if not p.health.get("ok", True):
            found.append((f"provider:{p.key}", f"{p.name} is failing", p.health.get("message", "")))
    return found


def watch(now=None):
    """Send each current problem once per cool-down. Returns the alert keys sent."""
    from apps.notifications import services as mail

    to = config.get("monitoring.alert_emails") or mail.team_recipients()
    cooldown = config.get("monitoring.cooldown_minutes") * 60
    sent = []
    for key, title, details in problems(now):
        if not cache.add(f"ops-alert:{key}", 1, cooldown):
            continue  # already sent within the cool-down
        for address in to:
            mail.send("ops/alert", address, {"title": title, "details": details, "environment": _environment()})
        sent.append(key)
    return sent


def _environment():
    from django.conf import settings

    return settings.ENVIRONMENT
