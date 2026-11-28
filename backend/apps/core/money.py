"""Catalogue money (CAT-08): amounts are stored in the minor unit (paise, cents …). A company billed in rupees sees
₹70,00,000 / 70 Lakh / 1.2 Cr; any other company sees its own currency ($85,000, Rs 9,900) — the company is the one in
the current tenant context (panel request, AI conversation, WhatsApp message)."""

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

UNITS = {
    "cr": 10_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "l": 100_000,
    "lac": 100_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "k": 1_000,
    "thousand": 1_000,
    "hazar": 1_000,
    "hazaar": 1_000,
    # Hindi / Bengali words (ENG-06)
    "लाख": 100_000,
    "करोड़": 10_000_000,
    "करोड": 10_000_000,
    "हज़ार": 1_000,
    "हजार": 1_000,
    "লাখ": 100_000,
    "লক্ষ": 100_000,
    "কোটি": 10_000_000,
    "হাজার": 1_000,
}


def indian_group(n: int) -> str:
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts) + "," + tail
    return ("-" if n < 0 else "") + s


def _company_currency():
    """The current company's billing currency when it is not the Indian rupee ("" = rupee formatting)."""
    from apps.tenancy.context import current_company_id

    company_id = current_company_id()
    if not company_id:
        return ""
    from django.core.cache import cache

    key = currency_cache_key(company_id)
    code = cache.get(key)
    if code is None:
        from apps.billing.currency import base
        from apps.tenancy.models import Company

        code = Company.objects.filter(pk=company_id).values_list("currency", flat=True).first() or base()
        cache.set(key, code, 3600)
    return "" if code == "INR" else code


def currency_cache_key(company_id):
    return f"company_currency:{company_id}"


def format_inr(paise, indian=True) -> str:
    if paise in (None, ""):
        return "—"
    code = _company_currency()
    if code:
        from apps.billing.currency import fmt

        return fmt(int(paise), code, decimals=False)
    rupees, rem = divmod(int(paise), 100)
    whole = indian_group(rupees) if indian else f"{rupees:,}"
    return f"₹{whole}" + (f".{rem:02d}" if rem else "")


def format_inr_short(paise) -> str:
    """₹1.2 Cr · ₹70 Lakh · ₹85,000."""
    if paise in (None, ""):
        return "—"
    if _company_currency():
        return format_inr(paise)
    rupees = Decimal(int(paise)) / 100
    for limit, word in ((10_000_000, "Cr"), (100_000, "Lakh")):
        if abs(rupees) >= limit:
            value = (rupees / limit).quantize(Decimal("0.01")).normalize()
            return f"₹{value:f} {word}"
    return format_inr(paise)


def parse_inr(value) -> int | None:
    """'70,00,000', '70 lakh', '1.2 Cr', '₹85000', 7000000 → paise. Empty → None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        return int(Decimal(str(value)) * 100)
    text = str(value).lower().replace("₹", "").replace("rs.", "").replace("rs", "").replace(",", "").strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([^\d\s.]*)", text)
    if not m or (m.group(2) and m.group(2) not in UNITS):
        raise ValidationError(f"Enter an amount like 70,00,000 or 70 lakh or 1.2 Cr (got {value!r}).")
    try:
        amount = Decimal(m.group(1)) * UNITS.get(m.group(2), 1)
    except InvalidOperation:
        raise ValidationError(f"Enter a valid amount (got {value!r}).") from None
    return int(amount * 100)
