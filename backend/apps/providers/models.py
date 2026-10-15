"""SA-09 / ENG-09: AI providers and the model used for each task (with fallback order). Platform tables.

Vendors are data (seeded, editable, more can be added in Super Admin). Keys are entered only in Super Admin and stored
encrypted (SEC-07). Voice / channel providers (STT, TTS, telephony, WhatsApp) join this app in Phases 5-6.
"""

from django.db import models

from apps.core.crypto import EncryptedTextField
from apps.core.models import BaseModel

CAPABILITIES = [("chat", "Chat / reasoning"), ("embedding", "Embeddings")]

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
    adapter = models.CharField(max_length=20, choices=ADAPTERS, default="openai")
    base_url = models.URLField(max_length=500)
    api_key = EncryptedTextField(blank=True)
    logo = models.CharField(max_length=500, blank=True, help_text="Image URL")
    capabilities = models.JSONField(default=list, blank=True)
    # [{"id": "model-name", "input_cost": 0.0, "output_cost": 0.0}] — cost per 1M tokens in the platform currency
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
