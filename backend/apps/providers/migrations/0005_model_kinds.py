"""Tag the seeded speech models as speech-to-text or text-to-speech, so a language's voice route only offers voice
models. Models without a kind (e.g. "default") can be used for both."""

from django.db import migrations

KINDS = {
    "saarika:v2.5": "stt",
    "bulbul:v2": "tts",
    "nova-3": "stt",
    "aura-2": "tts",
    "scribe_v1": "stt",
    "eleven_flash_v2_5": "tts",
    "eleven_multilingual_v2": "tts",
    "sonic-2": "tts",
    "chirp_2": "stt",
    "small": "stt",
    "medium": "stt",
    "large-v3-turbo": "stt",
    "kokoro-82m": "tts",
    "gpt-4o-transcribe": "stt",
    "gpt-4o-mini-tts": "tts",
}


def tag(apps, schema_editor):
    Provider = apps.get_model("providers", "Provider")
    for p in Provider.objects.exclude(vendor=""):
        rows = [{**m, "kind": KINDS[m["id"]]} if m["id"] in KINDS and "kind" not in m else m for m in p.available_models]
        if rows != p.available_models:
            p.available_models = rows
            p.save(update_fields=["available_models"])


class Migration(migrations.Migration):
    dependencies = [("providers", "0004_seed_voice")]
    operations = [migrations.RunPython(tag, migrations.RunPython.noop)]
