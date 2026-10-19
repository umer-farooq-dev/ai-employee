"""SA-09 / ENG-09 / SA-10 / SA-11: AI, speech and telephony providers, the model per task, languages and voices.
Platform tables.

Vendors are data (seeded, editable, more can be added in Super Admin). Keys are entered only in Super Admin and stored
encrypted (SEC-07). One vendor row can offer several capabilities (e.g. ElevenLabs: speech-to-text and voices) so a
key is entered once. WhatsApp joins in Phase 6 (Voice & channel providers); e-mail, SMS and payments in Phase 7.
"""

from django.db import models

from apps.core.crypto import EncryptedTextField
from apps.core.models import BaseModel

LLM_CAPABILITIES = [("chat", "Chat / reasoning"), ("embedding", "Embeddings")]
VOICE_CAPABILITIES = [
    ("stt", "Speech-to-text"),
    ("tts", "Text-to-speech"),
    ("telephony", "Telephony"),
    ("whatsapp", "WhatsApp"),
    ("push", "Push notifications"),
]
CAPABILITIES = LLM_CAPABILITIES + VOICE_CAPABILITIES

# What the AI engine asks for. Each task is routed to a provider + model in Super Admin (SDD: LLM gateway).
TASKS = [
    ("chat_dialog", "Chat conversations", "chat"),
    ("voice_dialog", "Voice conversations (fast)", "chat"),
    ("extraction", "CRM field extraction", "chat"),
    ("summary", "Conversation summaries", "chat"),
    ("scoring", "Lead scoring (intent)", "chat"),
    ("embedding", "Knowledge embeddings", "embedding"),
]
TASK_CAPABILITY = {key: cap for key, _label, cap in TASKS}


class Provider(BaseModel):
    ADAPTERS = [
        ("openai", "OpenAI-compatible API"),
        ("anthropic", "Anthropic Messages API"),
    ]

    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    adapter = models.CharField(max_length=20, choices=ADAPTERS, default="openai", help_text="LLM wire format")
    vendor = models.CharField(
        max_length=30, blank=True, help_text="Speech / telephony vendor (apps.providers.vendors); blank = LLM only"
    )
    base_url = models.URLField(max_length=500)
    api_key = EncryptedTextField(blank=True, help_text="The vendor's secret (API key, auth token, service account)")
    webhook_secret = EncryptedTextField(blank=True, help_text="Secret that signs the vendor's webhooks (SEC-13)")
    config = models.JSONField(default=dict, blank=True, help_text="Non-secret vendor settings: account id, region …")
    logo = models.CharField(max_length=500, blank=True, help_text="Image URL")
    capabilities = models.JSONField(default=list, blank=True)
    # [{"id": "model-name", "input_cost": 0.0, "output_cost": 0.0}] in the platform currency: LLM per 1M tokens,
    # speech-to-text per minute (input_cost), text-to-speech per 1M characters (input_cost)
    available_models = models.JSONField(default=list, blank=True)
    test_only = models.BooleanField(default=False, help_text="Free / test gateway: refused in production")
    is_active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    health = models.JSONField(default=dict, blank=True)  # {"ok": bool, "message": str, "checked_at": iso}

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def has_key(self):
        return bool(self.api_key)

    @property
    def model_ids(self):
        return [m["id"] for m in self.available_models]


class ModelRoute(BaseModel):
    """One provider + model for a task; several rows per task = fallback order (priority 1 first)."""

    task = models.CharField(max_length=30, choices=[(k, label) for k, label, _ in TASKS])
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="routes")
    model = models.CharField(max_length=200)
    params = models.JSONField(default=dict, blank=True, help_text='e.g. {"temperature": 0.3, "max_tokens": 800}')
    priority = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["task", "priority"]
        constraints = [models.UniqueConstraint(fields=["task", "priority"], name="unique_route_priority")]

    def __str__(self):
        return f"{self.task} #{self.priority}: {self.provider} / {self.model}"


# ------------------------------------------------------------------ SA-11 languages & voices (VOICE-07 … 09, 20)
SCRIPTS = [
    ("latin", "Latin"),
    ("devanagari", "Devanagari"),
    ("bengali", "Bengali"),
    ("gurmukhi", "Gurmukhi"),
    ("gujarati", "Gujarati"),
    ("oriya", "Odia"),
    ("tamil", "Tamil"),
    ("telugu", "Telugu"),
    ("kannada", "Kannada"),
    ("malayalam", "Malayalam"),
    ("arabic", "Arabic (Urdu)"),
]
# Phrases the runtime and the Voice Gateway say in each language (all editable per language in Super Admin)
LANGUAGE_TEXTS = [
    ("disclosure", "AI disclosure (start of every conversation)"),
    ("recording_consent", "Recording announcement"),
    ("greeting", "Default greeting"),
    ("fillers", "Fillers while a tool runs (one per line)"),
    ("transfer", "Before transferring to a person"),
    ("no_agent", "When no person is available"),
    ("voicemail", "Voicemail message (outbound)"),
    ("silence", "When the caller is silent"),
    ("goodbye", "Goodbye"),
    # website chat widget (CHAT-02 / CHAT-03); {name} = the team member
    ("chat_launcher", "Chat widget: launcher button"),
    ("chat_placeholder", "Chat widget: message box"),
    ("chat_send", "Chat widget: send button"),
    ("chat_human", "Chat widget: talk to a person"),
    ("chat_callback", "Chat widget: request a callback"),
    ("chat_enquiry", "Chat widget: send an enquiry"),
    ("chat_book", "Chat widget: book an appointment"),
    ("chat_waiting", "Chat widget: connecting to a person"),
    ("chat_joined", "Chat widget: a person joined ({name})"),
    ("chat_ai_back", "Chat widget: back with the AI"),
    ("chat_ended", "Chat widget: chat ended"),
    ("chat_restart", "Chat widget: start a new chat"),
    ("chat_name", "Chat widget form: name"),
    ("chat_phone", "Chat widget form: mobile number"),
    ("chat_email", "Chat widget form: e-mail"),
    ("chat_message", "Chat widget form: message"),
    ("chat_submit", "Chat widget form: submit"),
    ("chat_thanks", "Chat widget form: thank you"),
    ("chat_error", "Chat widget: something went wrong"),
    # WhatsApp (WA-08)
    ("wa_opted_out", "WhatsApp: reply to an opt-out keyword"),
    ("wa_opted_in", "WhatsApp: reply to an opt-in keyword"),
]
CHAT_TEXT_KEYS = [k for k, _ in LANGUAGE_TEXTS if k.startswith("chat_")]


class Language(BaseModel):
    """A language the AI Employees can speak. New language = a row + routes + voices + texts (no code)."""

    code = models.SlugField(max_length=10, unique=True, help_text="Short code used everywhere, e.g. hi")
    name = models.CharField(max_length=60)
    native_name = models.CharField(max_length=60, blank=True)
    locale = models.CharField(max_length=20, help_text="BCP-47 locale for speech providers, e.g. hi-IN")
    script = models.CharField(
        max_length=20, choices=SCRIPTS, default="latin", help_text="Writing system, used to detect the language"
    )
    texts = models.JSONField(default=dict, blank=True, help_text="{key: text} — see LANGUAGE_TEXTS")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Voice(BaseModel):
    """VOICE-09: voice catalogue — a text-to-speech voice of a provider for one language."""

    GENDERS = [("female", "Female"), ("male", "Male"), ("neutral", "Neutral")]

    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name="voices")
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="voices")
    provider_voice_id = models.CharField(max_length=200)
    name = models.CharField(max_length=80)
    gender = models.CharField(max_length=10, choices=GENDERS, default="female")
    style = models.CharField(max_length=80, blank=True, help_text="e.g. warm, professional, energetic")
    sample = models.CharField(max_length=500, blank=True, help_text="Audio sample URL")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["language__sort_order", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["language", "provider", "provider_voice_id"], name="unique_voice")
        ]

    def __str__(self):
        return f"{self.name} ({self.language.code})"


class SpeechRoute(BaseModel):
    """VOICE-08 / VOICE-21: speech-to-text or text-to-speech provider for a language; priority 2+ = failover."""

    KINDS = [("stt", "Speech-to-text"), ("tts", "Text-to-speech")]

    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name="routes")
    kind = models.CharField(max_length=3, choices=KINDS)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="speech_routes")
    model = models.CharField(max_length=200)
    voice = models.ForeignKey(
        Voice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="Default voice (TTS)"
    )
    params = models.JSONField(default=dict, blank=True)
    priority = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["language", "kind", "priority"]
        constraints = [
            models.UniqueConstraint(fields=["language", "kind", "priority"], name="unique_speech_route_priority")
        ]

    def __str__(self):
        return f"{self.language.code} {self.kind} #{self.priority}: {self.provider} / {self.model}"
