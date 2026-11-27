"""Website wording for businesses in any country (was written for India). Old text → new text; used by the seed
content and by migration 0009, which changes a published text only while it is still the original wording."""

GLOBAL_COPY = {
    "Works 24/7 in Indian languages": "Works 24/7 in your customers' languages",
    "It answers calls, WhatsApp and website chats in Hindi, English and Bengali, qualifies your leads and books "
    "appointments — while your team focuses on closing.": "It answers calls, WhatsApp and website chats in your "
    "customers' language, qualifies your leads and books appointments — while your team focuses on closing.",
    "Hindi, English, Bengali and mixed Hinglish.": "English, Urdu, Hindi, Bengali and more, even when customers mix "
    "languages.",
    "Hindi, English and Bengali at launch, including mixed Hinglish. More Indian languages are added over time.": (
        "English, Urdu, Hindi and Bengali today, including mixed speech like Hinglish. More languages are added over "
        "time, and each business chooses the ones its customers speak."
    ),
    "Answers and makes calls in Indian languages, transfers to your team when needed.": "Answers and makes calls in "
    "your customers' languages, transfers to your team when needed.",
    "We help Indian businesses answer every customer, every time.": "We help businesses answer every customer, every "
    "time.",
    "Built for India": "Built for every market",
    "Indian languages, Indian numbers, Indian businesses.": "Local languages, local phone numbers and prices in your "
    "customers' currency.",
}


def apply(value):
    """Replace old wording anywhere inside section content (dicts, lists, strings)."""
    if isinstance(value, dict):
        return {k: apply(v) for k, v in value.items()}
    if isinstance(value, list):
        return [apply(v) for v in value]
    if isinstance(value, str):
        return GLOBAL_COPY.get(value, value)
    return value
