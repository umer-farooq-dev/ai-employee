"""Reference data for India (not business settings): states and union territories, GSTIN format, phone input."""

import re

from django.core.exceptions import ValidationError

STATES = [
    "Andaman and Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]
STATE_CHOICES = [(s, s) for s in STATES]

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def validate_gstin(value):
    if value and not GSTIN_RE.match(value.upper()):
        raise ValidationError("Enter a valid 15-character GSTIN, e.g. 27ABCDE1234F1Z5.")


def normalise_phone(value: str) -> str:
    """Accept '98765 43210', '09876543210' or '+91 98765 43210' and return E.164 (+91 is the default country)."""
    digits = re.sub(r"[^\d+]", "", value or "")
    if digits.startswith("+"):
        return digits
    digits = digits.lstrip("0")
    return f"+91{digits}" if len(digits) == 10 else f"+{digits}"
