"""Fixed-window rate limit for website forms (SEC-09). Rates look like "10/hour" and come from the settings registry."""

import time

from django.core.cache import cache

PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def allow(scope: str, ident: str, rate: str) -> bool:
    count, period = rate.split("/")
    seconds = PERIODS[period]
    key = f"rl:{scope}:{ident}:{int(time.time() // seconds)}"
    if cache.add(key, 1, seconds):
        return True
    try:
        return cache.incr(key) <= int(count)
    except ValueError:  # expired between add and incr
        return cache.add(key, 1, seconds)
