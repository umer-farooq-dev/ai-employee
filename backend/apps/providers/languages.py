"""The languages the platform speaks, read from Super Admin → Languages & Voices (SA-11). Every screen, form and the
AI runtime ask here instead of a fixed list, so a new language needs no code (VOICE-20)."""

from .models import Language


def active():
    return list(Language.objects.filter(is_active=True))


def choices():
    """[(code, name)] of the switched-on languages, in display order. Safe to pass as callable form choices."""
    return [(lang.code, lang.name) for lang in active()]


def codes():
    return [code for code, _ in choices()]


def names():
    return dict(Language.objects.values_list("code", "name"))


def get(code):
    return Language.objects.filter(code=code).first()


def text(code, key, default=""):
    """A phrase of one language (LANGUAGE_TEXTS), falling back to the first active language that has it."""
    lang = get(code)
    value = (lang.texts or {}).get(key) if lang else None
    if value:
        return value
    for other in active():
        if (other.texts or {}).get(key):
            return other.texts[key]
    return default


def script_map():
    """{script: language code} for language detection; the first active language of a script wins."""
    out = {}
    for lang in active():
        out.setdefault(lang.script, lang.code)
    return out
