"""Indian money (CAT-08): amounts are stored in paise; shown as ₹70,00,000, 70 Lakh or 1.2 Cr."""

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


def format_inr(paise, indian=True) -> str:
    if paise in (None, ""):
        return "—"
    rupees, rem = divmod(int(paise), 100)
    whole = indian_group(rupees) if indian else f"{rupees:,}"
    return f"₹{whole}" + (f".{rem:02d}" if rem else "")


def format_inr_short(paise) -> str:
    """₹1.2 Cr · ₹70 Lakh · ₹85,000."""
    if paise in (None, ""):
        return "—"
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
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([a-z]*)", text)
    if not m or (m.group(2) and m.group(2) not in UNITS):
        raise ValidationError(f"Enter an amount like 70,00,000 or 70 lakh or 1.2 Cr (got {value!r}).")
    try:
        amount = Decimal(m.group(1)) * UNITS.get(m.group(2), 1)
    except InvalidOperation:
        raise ValidationError(f"Enter a valid amount (got {value!r}).") from None
    return int(amount * 100)
