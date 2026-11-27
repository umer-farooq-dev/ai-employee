"""Countries and currencies for worldwide pricing. Reference data (country → its currency, names, symbols, how many
decimals) comes from the Unicode CLDR via Babel. What is sold in which currency, exchange rates, explicit prices and
the payment gateway per currency are data in Super Admin (Billing → Currencies, Plans).

Amounts are integers in the currency's minor unit (paise, cents …), as the gateways expect them. The model fields
keep their historic *_paise names; for any currency other than INR they hold that currency's minor unit."""

import logging
from decimal import ROUND_HALF_UP, Decimal
from functools import cache, lru_cache

from babel import Locale, UnknownLocaleError
from babel.numbers import format_currency, get_currency_name, get_currency_precision, get_territory_currencies

from apps.platform_config.services import get as setting

logger = logging.getLogger(__name__)
EN = Locale("en")
# Stripe takes these zero-decimal (by ISO) currencies as two-decimal amounts (ends in 00): same for Razorpay
TWO_DECIMAL_ON_GATEWAYS = {"ISK"}


# ------------------------------------------------------------------ reference data
@cache
def countries():
    """[(code, name)] of every country / territory that has a currency, by name."""
    return sorted(
        ((code, name) for code, name in EN.territories.items() if len(code) == 2 and code.isalpha() and _own(code)),
        key=lambda row: row[1],
    )


def _own(country):
    try:
        found = get_territory_currencies(country, tender=True)
    except Exception:  # noqa: BLE001 — unknown territory
        return ""
    return found[0] if found else ""


@cache
def country_currency(country):
    """ISO currency used in a country today ("" when unknown)."""
    return _own((country or "").upper())


def country_name(country):
    return EN.territories.get((country or "").upper(), country or "")


def valid_country(country):
    return bool(country) and len(country) == 2 and bool(country_currency(country))


def name(code):
    return get_currency_name(code, locale="en")


def exponent(code):
    """Digits of the minor unit as the payment gateways count them (USD 2, JPY 0, KWD 3)."""
    return 2 if code in TWO_DECIMAL_ON_GATEWAYS else get_currency_precision(code)


def to_minor(major, code):
    return int((Decimal(str(major)) * 10 ** exponent(code)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_major(minor, code):
    return Decimal(minor or 0) / 10 ** exponent(code)


@lru_cache(maxsize=512)
def _locale(country):
    """English with the country's number style and symbols (en_IN: ₹1,23,456 · en_DE: 1.234 €)."""
    try:
        return Locale.parse(f"en_{country.upper()}") if country else EN
    except (UnknownLocaleError, ValueError):
        return EN


def fmt(minor, code="", country="", decimals=True):
    """Minor units → "$1,234.50", "₹1,23,456", "Rs 9,900" in the style of the country (default: the currency's)."""
    code = code or base()
    country = country or _home_country(code)
    loc = _locale(country)
    amount = to_major(minor, code)
    if decimals is False:
        pattern = loc.currency_formats["standard"].pattern.split(";")[0]
        pattern = pattern.replace(".00", "").replace(".000", "")
        text = format_currency(amount, code, format=pattern, locale=loc, currency_digits=False)
    else:
        text = format_currency(amount, code, locale=loc)
    symbol = loc.currency_symbols.get(code, code)
    if symbol[-1:].isalpha() and text.lstrip("-").startswith(symbol) and not text.lstrip("-")[len(symbol)].isspace():
        text = text.replace(symbol, symbol + " ", 1)  # "Rs 9,900", "AED 99" (not "Rs9,900")
    return text


@lru_cache(maxsize=256)
def _home_country(code):
    """The country a currency belongs to, for its number style (INR → IN, PKR → PK; EUR → international)."""
    if code == "EUR":
        return ""
    if country_currency(code[:2]) == code:  # ISO 4217: country code + one letter
        return code[:2]
    return next((c for c, _ in countries() if country_currency(c) == code), "")


# ------------------------------------------------------------------ what the platform sells in
def base():
    """The currency plan prices are entered in (System Settings → Localisation → Currency)."""
    return setting("locale.currency") or "INR"


def offered():
    """{code: Currency} of the active currencies."""
    from .models import Currency

    return {c.code: c for c in Currency.objects.filter(is_active=True)}


def rate(code, rows=None):
    """Units of `code` per 1 unit of the base currency, or None when unknown."""
    if code == base():
        return Decimal(1)
    row = (rows if rows is not None else offered()).get(code)
    return row.rate if row and row.rate else None


def for_country(country, rows=None):
    """The currency a visitor / company from this country pays in: its own when the platform sells in it (active
    with an exchange rate), else the fallback currency setting, else the base currency."""
    rows = offered() if rows is None else rows
    for code in (country_currency(country), setting("billing.fallback_currency")):
        if code and (code == base() or (code in rows and rows[code].rate)):
            return code
    return base()


def nice(major):
    """A converted price rounded the way people price things: 35.98 → 36, 9,897 → 9,900, 128,456 → 128,000."""
    if major <= 0:
        return Decimal(0)
    if major < 100:
        step = Decimal(1)
    else:
        step = Decimal(10) ** (len(str(int(major))) - 2)
    return (major / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def convert(minor, code, rows=None, rounded=True):
    """An amount in the base currency → the same value in `code` (None when there is no rate)."""
    if minor is None:
        return None
    if code == base():
        return minor
    r = rate(code, rows)
    if r is None:
        return None
    major = to_major(minor, base()) * r
    return to_minor(nice(major) if rounded else major, code)


def to_base(minor, code, rows=None):
    """An amount in `code` → base currency minor units at today's rate (Super Admin totals; 0 when no rate)."""
    if not minor or not code or code == base():
        return minor or 0
    r = rate(code, rows)
    if not r:
        return 0
    return to_minor(to_major(minor, code) / r, base())


def plan_amount(plan, interval, code, rows=None):
    """The plan's price per interval in `code`: the price set for that currency, else converted from the base
    currency price. None = not sold online (custom plan or no price)."""
    field = "yearly_paise" if interval == "yearly" else "monthly_paise"
    own = next((p for p in plan.prices.all() if p.currency == code), None)
    if own and getattr(own, field) is not None:
        return getattr(own, field)
    base_amount = plan.price_yearly_paise if interval == "yearly" else plan.price_monthly_paise
    return convert(base_amount, code, rows)


# ------------------------------------------------------------------ exchange rates (Super Admin button + daily run)
def refresh_rates(now=None):
    """Fetch today's rates for the base currency from the rates URL setting → number of currencies updated."""
    from django.utils import timezone

    from apps.providers.adapters import ProviderError, _request

    from .models import Currency

    url = (setting("billing.fx_rates_url") or "").replace("{base}", base())
    if not url:
        raise ProviderError("Set the exchange rates address in System Settings → Billing first.")
    data = _request("GET", url, {}, timeout=20)
    rates = data.get("rates") or data.get("conversion_rates") or {}
    if not rates:
        raise ProviderError("The exchange rates service returned no rates.")
    now = now or timezone.now()
    done = 0
    for row in Currency.objects.filter(manual_rate=False):
        value = rates.get(row.code)
        if value:
            row.rate, row.rate_updated_at = Decimal(str(value)).quantize(Decimal("0.000001")), now
            row.save(update_fields=["rate", "rate_updated_at", "updated_at"])
            done += 1
    return done


def refresh_if_due(now=None):
    """Daily: rates older than 20 hours are fetched again (System Settings → Billing → update automatically)."""
    from datetime import timedelta

    from django.db.models import F
    from django.utils import timezone

    from .models import Currency

    if not setting("billing.fx_auto_update"):
        return 0
    now = now or timezone.now()
    rows = Currency.objects.filter(manual_rate=False)
    oldest = rows.order_by(F("rate_updated_at").asc(nulls_first=True)).values_list("rate_updated_at", flat=True)
    last = oldest.first()
    if not rows.exists() or (last and last > now - timedelta(hours=20)):
        return 0
    try:
        return refresh_rates(now)
    except Exception as exc:  # noqa: BLE001 — a rates outage must not stop billing
        logger.warning("exchange rates update failed: %s", exc)
        return 0
