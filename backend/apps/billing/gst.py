"""SUB-06: Indian GST arithmetic. State codes are fixed by law (first two digits of a GSTIN); rates and the seller's
state are settings (Super Admin → System Settings → Billing & GST)."""

import re
from decimal import ROUND_HALF_UP, Decimal

STATES = [
    ("01", "Jammu and Kashmir"),
    ("02", "Himachal Pradesh"),
    ("03", "Punjab"),
    ("04", "Chandigarh"),
    ("05", "Uttarakhand"),
    ("06", "Haryana"),
    ("07", "Delhi"),
    ("08", "Rajasthan"),
    ("09", "Uttar Pradesh"),
    ("10", "Bihar"),
    ("11", "Sikkim"),
    ("12", "Arunachal Pradesh"),
    ("13", "Nagaland"),
    ("14", "Manipur"),
    ("15", "Mizoram"),
    ("16", "Tripura"),
    ("17", "Meghalaya"),
    ("18", "Assam"),
    ("19", "West Bengal"),
    ("20", "Jharkhand"),
    ("21", "Odisha"),
    ("22", "Chhattisgarh"),
    ("23", "Madhya Pradesh"),
    ("24", "Gujarat"),
    ("26", "Dadra and Nagar Haveli and Daman and Diu"),
    ("27", "Maharashtra"),
    ("29", "Karnataka"),
    ("30", "Goa"),
    ("31", "Lakshadweep"),
    ("32", "Kerala"),
    ("33", "Tamil Nadu"),
    ("34", "Puducherry"),
    ("35", "Andaman and Nicobar Islands"),
    ("36", "Telangana"),
    ("37", "Andhra Pradesh"),
    ("38", "Ladakh"),
    ("97", "Other Territory"),
]
NAMES = dict(STATES)
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def state_choices():
    return [("", "— choose —"), *STATES]


def clean_gstin(value):
    value = (value or "").strip().upper()
    if value and (not GSTIN.match(value) or value[:2] not in NAMES):
        from django.core.exceptions import ValidationError

        raise ValidationError("Enter a valid 15-character GSTIN, e.g. 27ABCDE1234F1Z5.")
    return value


def state_code(gstin="", state=""):
    """The buyer's state: the GSTIN prefix wins; else the state name (or code) from the profile."""
    if gstin and gstin[:2] in NAMES:
        return gstin[:2]
    state = (state or "").strip()
    if state in NAMES:
        return state
    return next((code for code, name in STATES if name.lower() == state.lower()), "")


def paise(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def split(amount_paise, rate, seller_code, buyer_code):
    """Tax on a taxable amount: CGST + SGST within the seller's state (or when the buyer's state is unknown),
    IGST across states. → {intra_state, cgst, sgst, igst, total}"""
    rate = Decimal(str(rate))
    intra = not buyer_code or buyer_code == seller_code
    if intra:
        half = paise(Decimal(amount_paise) * rate / 2 / 100)
        cgst, sgst, igst = half, half, 0
    else:
        cgst, sgst, igst = 0, 0, paise(Decimal(amount_paise) * rate / 100)
    return {"intra_state": intra, "cgst": cgst, "sgst": sgst, "igst": igst, "total": amount_paise + cgst + sgst + igst}


def taxable_from_inclusive(gross_paise, rate):
    """When prices are shown with GST included: the taxable value inside a gross price."""
    return paise(Decimal(gross_paise) * 100 / (100 + Decimal(str(rate))))
