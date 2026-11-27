"""The visitor's country and currency (website prices, registration). Order: ?region=US or ?currency=USD (kept in a
cookie), the cookie, Cloudflare's CF-IPCountry header, the browser language (en-US), the default country setting."""

from . import currency

COUNTRY_COOKIE, CURRENCY_COOKIE, YEAR = "region", "currency", 365 * 24 * 3600
NOT_COUNTRIES = {"XX", "T1", "EU", "ZZ"}  # Cloudflare: unknown / Tor; not a country


def _country_from(value):
    value = (value or "").strip().upper()
    return value if value not in NOT_COUNTRIES and currency.valid_country(value) else ""


def visitor_country(request):
    if not hasattr(request, "_country"):
        found = (
            _country_from(request.GET.get("region"))
            or _country_from(request.COOKIES.get(COUNTRY_COOKIE))
            or _country_from(request.headers.get("CF-IPCountry"))
        )
        if not found:
            for part in request.headers.get("Accept-Language", "").split(","):
                tag = part.split(";")[0].strip()
                if "-" in tag and (found := _country_from(tag.rsplit("-", 1)[1])):
                    break
        if not found:
            from apps.platform_config.services import get as setting

            found = _country_from(setting("locale.default_phone_country")) or currency.base()[:2]
        request._country = found
    return request._country


def _currency_from(value, rows):
    value = (value or "").strip().upper()
    return value if value == currency.base() or (value in rows and rows[value].rate) else ""


def visitor_currency(request):
    if not hasattr(request, "_currency"):
        rows = currency.offered()
        chosen = _currency_from(request.GET.get("currency"), rows)
        if not chosen and not request.GET.get("region"):  # a newly chosen country brings its own currency
            chosen = _currency_from(request.COOKIES.get(CURRENCY_COOKIE), rows)
        request._currency = chosen or currency.for_country(visitor_country(request), rows)
    return request._currency


def sellable(rows=None):
    """[(code, name)] the visitor can switch prices to: the base currency and active currencies with a rate."""
    rows = currency.offered() if rows is None else rows
    codes = {currency.base(), *(code for code, row in rows.items() if row.rate)}
    return [(code, f"{code} — {currency.name(code)}") for code in sorted(codes)]


def context(request):
    """{{ visitor_country }} in every template (phone fields start on it); worked out only when a template uses it."""
    from django.utils.functional import SimpleLazyObject

    return {"visitor_country": SimpleLazyObject(lambda: visitor_country(request).lower())}


class RegionMiddleware:
    """Remembers a country or currency picked with ?region= / ?currency= for a year."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        picked_country = _country_from(request.GET.get("region"))
        if picked_country:
            response.set_cookie(
                COUNTRY_COOKIE, picked_country, max_age=YEAR, samesite="Lax", secure=request.is_secure()
            )
            response.delete_cookie(CURRENCY_COOKIE)
        if request.GET.get("currency"):
            code = _currency_from(request.GET["currency"], currency.offered())
            if code:
                response.set_cookie(CURRENCY_COOKIE, code, max_age=YEAR, samesite="Lax", secure=request.is_secure())
        return response
