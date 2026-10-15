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


# ------------------------------------------------------------------ language, dates, masking (ENG-06, ENG-07, ENG-10)
def detect_language(text: str, default="en") -> str:
    """Script-based: Devanagari → hi, Bengali → bn, otherwise default (romanised Hinglish counts as the default)."""
    counts = {"hi": 0, "bn": 0}
    for ch in text or "":
        if "\u0900" <= ch <= "\u097f":
            counts["hi"] += 1
        elif "\u0980" <= ch <= "\u09ff":
            counts["bn"] += 1
    lang = max(counts, key=counts.get)
    return lang if counts[lang] >= 2 else default


WEEKDAYS = {
    0: ("monday", "mon", "somvar", "सोमवार", "সোমবার"),
    1: ("tuesday", "tue", "mangalvar", "मंगलवार", "মঙ্গলবার"),
    2: ("wednesday", "wed", "budhvar", "बुधवार", "বুধবার"),
    3: ("thursday", "thu", "guruvar", "गुरुवार", "বৃহস্পতিবার"),
    4: ("friday", "fri", "shukravar", "शुक्रवार", "শুক্রবার"),
    5: ("saturday", "sat", "shanivar", "शनिवार", "শনিবার"),
    6: ("sunday", "sun", "ravivar", "itvar", "रविवार", "इतवार", "রবিবার"),
}
RELATIVE = {
    0: ("today", "aaj", "आज", "আজ"),
    1: ("tomorrow", "kal", "कल", "কাল", "agle din"),
    2: ("day after tomorrow", "parso", "parson", "परसों", "পরশু"),
}
MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}


def parse_indian_date(text, today):
    """'2026-11-15', '15/11/2026', '15 Nov', 'kal', 'parso', 'next Sunday', 'रविवार' → date, else None."""
    import datetime as dt

    if isinstance(text, dt.date):
        return text
    t = " ".join(str(text or "").lower().split())
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)(?:\s+(\d{4}))?", t) or re.search(
        r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t
    )
    if m:
        a, b, year = m.groups()
        day, month = (a, b) if a.isdigit() else (b, a)
        if month in MONTHS:
            try:
                d = dt.date(int(year) if year else today.year, MONTHS[month], int(day))
            except ValueError:
                return None
            return d if year or d >= today else d.replace(year=d.year + 1)
    for offset in (2, 1, 0):  # longest phrases first ("day after tomorrow" before "tomorrow")
        if any(re.search(rf"(^|\W){re.escape(w)}($|\W)", t) for w in RELATIVE[offset]):
            return today + dt.timedelta(days=offset)
    for weekday, names in WEEKDAYS.items():
        if any(re.search(rf"(^|\W){re.escape(n)}($|\W)", t) for n in names):
            ahead = (weekday - today.weekday()) % 7 or 7
            if any(w in t for w in ("next", "agle", "अगले", "পরের")) and ahead < 7:
                ahead += 7 if (weekday - today.weekday()) % 7 == 0 else 0
            return today + dt.timedelta(days=ahead)
    if "next week" in t or "agle hafte" in t:
        return today + dt.timedelta(days=7)
    return None


PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s-]{8,}\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_pii(text: str) -> str:
    """ENG-10: phone numbers and e-mails masked in logs, e.g. +91******3210, r***@example.com."""
    text = EMAIL_RE.sub(lambda m: m.group(0)[0] + "***@" + m.group(0).split("@", 1)[1], str(text))
    return PHONE_RE.sub(lambda m: re.sub(r"\d", "*", m.group(0)[:-4]) + m.group(0)[-4:], text)
