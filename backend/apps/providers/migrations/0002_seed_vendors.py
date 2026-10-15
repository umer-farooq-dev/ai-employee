"""Seed the popular AI vendors (SA-09). Data, not code: every row is editable in Super Admin → AI Settings and more
vendors can be added there. All start switched off with no key; keys are entered only in Super Admin."""

from django.db import migrations

from apps.platform_config.registry import SETTINGS

CHAT, EMB = "chat", "embedding"
VENDORS = [
    # key, name, description, adapter, base_url, capabilities, test_only
    ("openai", "OpenAI", "GPT models and embeddings", "openai", "https://api.openai.com/v1", [CHAT, EMB], False),
    (
        "gemini",
        "Google Gemini",
        "Gemini models and embeddings",
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        [CHAT, EMB],
        False,
    ),
    ("anthropic", "Anthropic", "Claude models", "anthropic", "https://api.anthropic.com", [CHAT], False),
    ("xai", "xAI", "Grok models", "openai", "https://api.x.ai/v1", [CHAT], False),
    ("groq", "Groq", "Fast open models", "openai", "https://api.groq.com/openai/v1", [CHAT], False),
    ("mistral", "Mistral AI", "Mistral models and embeddings", "openai", "https://api.mistral.ai/v1", [CHAT, EMB], False),
    ("deepseek", "DeepSeek", "DeepSeek models", "openai", "https://api.deepseek.com/v1", [CHAT], False),
    ("openrouter", "OpenRouter", "Many vendors behind one key", "openai", "https://openrouter.ai/api/v1", [CHAT], False),
    ("together", "Together AI", "Open models and embeddings", "openai", "https://api.together.xyz/v1", [CHAT, EMB], False),
    ("cerebras", "Cerebras", "Very fast open models", "openai", "https://api.cerebras.ai/v1", [CHAT], False),
    (
        "freellmapi",
        "FreeLLMAPI",
        "Self-hosted free-tier pool — testing only",
        "openai",
        "http://127.0.0.1:3001/v1",
        [CHAT],
        True,
    ),
    (
        "omniroute",
        "OmniRoute",
        "Self-hosted free-model router — testing only",
        "openai",
        "http://127.0.0.1:20128/v1",
        [CHAT],
        True,
    ),
]


def seed(apps, schema_editor):
    Provider = apps.get_model("providers", "Provider")
    for order, (key, name, desc, adapter, url, caps, test_only) in enumerate(VENDORS, start=1):
        Provider.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "description": desc,
                "adapter": adapter,
                "base_url": url,
                "capabilities": caps,
                "test_only": test_only,
                "sort_order": order * 10,
            },
        )
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for s in SETTINGS:
        if s.key.startswith("ai."):
            PlatformSetting.objects.get_or_create(key=s.key, defaults={"value": s.default})


class Migration(migrations.Migration):
    dependencies = [("providers", "0001_initial"), ("platform_config", "0003_seed_phase2_settings")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
