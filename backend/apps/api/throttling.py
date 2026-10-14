"""SEC-09: API rate limits per user, per IP and per company; the rates come from Super Admin → Security."""

from rest_framework import throttling

from apps.platform_config import services as config


class UserRateThrottle(throttling.UserRateThrottle):
    def get_rate(self):
        return config.get("security.api_rate_user")


class AnonRateThrottle(throttling.AnonRateThrottle):
    def get_rate(self):
        return config.get("security.api_rate_anon")


class CompanyRateThrottle(throttling.SimpleRateThrottle):
    scope = "company"

    def get_rate(self):
        return config.get("security.api_rate_company")

    def get_cache_key(self, request, view):
        company = getattr(request, "company", None)
        return self.cache_format % {"scope": self.scope, "ident": company.id} if company else None
