"""AI Employees (M06: EMP-01 … EMP-14), conversations, tool log (TOOL-14) and AI usage (ENG-11, USE-01).

An AI Employee is configuration run by one shared engine (apps.agents.runtime).
Company-owned tables (TenantModel + RLS).
"""

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantModel


class AIEmployee(TenantModel):
    DRAFT, ACTIVE, PAUSED, ARCHIVED = "draft", "active", "paused", "archived"
    STATUSES = [(DRAFT, "Draft"), (ACTIVE, "Active"), (PAUSED, "Paused"), (ARCHIVED, "Archived")]
    TONES = [("friendly", "Friendly"), ("formal", "Formal")]

    name = models.CharField(max_length=80)
    industry = models.ForeignKey("industries.Industry", on_delete=models.PROTECT, related_name="+")
    role = models.ForeignKey("roles_tools.EmployeeRole", on_delete=models.PROTECT, related_name="+")
    template_version = models.ForeignKey(
        "industries.TemplateVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    avatar = models.CharField(max_length=500, blank=True, help_text="Image URL")
    # EMP-04: {"description": str, "tone": "friendly" | "formal", "gender": str}
    persona = models.JSONField(default=dict, blank=True)
    greetings = models.JSONField(default=dict, blank=True, help_text="{language: greeting}; empty = template greeting")
    primary_language = models.CharField(max_length=10, default="en")
    languages = models.JSONField(default=list, blank=True, help_text="All languages incl. the primary one")
    voices = models.JSONField(default=dict, blank=True, help_text="EMP-05 (Phase 5): {language: voice}, speed")
    # EMP-09 rules: working_hours, after_hours, max_call_minutes, transfer_user_ids, escalation_triggers,
    # fallback {lang: text}, fallback_action, disclosure {lang: text}, recording, consent {lang: text},
    # follow_up {enabled, after_hours}, restricted_topics [str]
    rules = models.JSONField(default=dict, blank=True)
    qualification = models.JSONField(default=list, blank=True, help_text="Ordered questions; empty = template flow")
    tools = models.JSONField(
        default=dict, blank=True, help_text="TOOL-13: {tool key: true/false}; missing = role default"
    )
    calendar_resources = models.JSONField(
        default=list, blank=True, help_text="EMP-08: resource ids it may book; empty = all"
    )
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT, db_index=True)
    config_version = models.PositiveIntegerField(default=1)
    tested_version = models.PositiveIntegerField(
        null=True, blank=True, help_text="EMP-11: version that passed the test"
    )
    wizard_step = models.PositiveSmallIntegerField(default=1)
    activated_at = models.DateTimeField(null=True, blank=True)
    paused_reason = models.CharField(max_length=255, blank=True)
    paused_by_platform = models.BooleanField(default=False, help_text="SA-08: paused by Super Admin for abuse")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def test_passed(self):
        return self.tested_version == self.config_version


class ConfigVersion(TenantModel):
    """EMP-12: every saved change (who / when / what) with a full snapshot."""

    employee = models.ForeignKey(AIEmployee, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    changes = models.JSONField(default=list, blank=True, help_text="Changed settings")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_by_email = models.CharField(max_length=254, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["employee", "version"], name="uniq_employee_version")]


class Conversation(TenantModel):
    CHANNELS = [("test", "Test console"), ("web_chat", "Website chat"), ("whatsapp", "WhatsApp"), ("voice", "Voice")]
    CHAT_CHANNELS = ("web_chat", "whatsapp")  # typed channels with the shared inbox (WA-06, CHAT-06)
    ACTIVE, ENDED = "active", "ended"
    AI, WAITING, HUMAN = "ai", "waiting", "human"
    HANDLERS = [(AI, "AI Employee"), (WAITING, "Waiting for a person"), (HUMAN, "Team member")]

    employee = models.ForeignKey(AIEmployee, on_delete=models.CASCADE, related_name="conversations")
    employee_version = models.PositiveIntegerField(default=1)
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    channel = models.CharField(max_length=10, choices=CHANNELS, default="test")
    direction = models.CharField(max_length=10, default="inbound")
    is_test = models.BooleanField(default=False)
    status = models.CharField(max_length=10, default=ACTIVE, db_index=True)
    customer = models.JSONField(default=dict, blank=True, help_text="Identity from the channel: phone, name, email")
    language = models.CharField(max_length=10, blank=True)
    summary = models.TextField(blank=True)
    requirement = models.JSONField(default=dict, blank=True, help_text="ENG-06 extracted fields")
    sentiment = models.CharField(max_length=20, blank=True)
    intent = models.CharField(max_length=10, blank=True)
    intent_score = models.PositiveSmallIntegerField(null=True, blank=True)
    intent_confidence = models.FloatField(null=True, blank=True)
    outcome = models.CharField(max_length=255, blank=True)
    follow_up_required = models.BooleanField(default=False)
    score_label_after = models.CharField(max_length=10, blank=True)
    tool_calls = models.PositiveIntegerField(default=0)
    # runtime state: disclosed flag, records created by a test conversation (removed when the test ends)
    state = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # shared inbox: who answers now (the AI pauses while a person has taken over) and the team member in charge
    handled_by = models.CharField(max_length=10, choices=HANDLERS, default=AI, db_index=True)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="inbox_conversations"
    )

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["company", "employee", "-started_at"])]

    @property
    def customer_name(self):
        return (self.lead.name if self.lead_id else "") or (self.customer or {}).get("name", "")


class Message(TenantModel):
    """Transcript line. ponytail: one table; monthly partitions (SDD) when volume needs them."""

    ROLES = [("customer", "Customer"), ("ai", "AI"), ("human", "Human"), ("system", "System"), ("tool", "Tool")]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLES)
    content = models.TextField(blank=True)
    language = models.CharField(max_length=10, blank=True)
    citations = models.JSONField(default=list, blank=True, help_text="KB-11: knowledge chunks used")
    meta = models.JSONField(default=dict, blank=True, help_text="Tool calls, guardrail flags, provider/model")

    class Meta:
        ordering = ["created_at"]


class ToolInvocation(TenantModel):
    """TOOL-14: inputs, outputs, status and duration per call."""

    OK, ERROR, DENIED, TIMEOUT = "ok", "error", "denied", "timeout"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="tool_invocations")
    tool_key = models.CharField(max_length=60)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, default=OK)
    latency_ms = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=120)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "idempotency_key"], name="uniq_tool_idempotency"),
        ]


class UsageEvent(TenantModel):
    """ENG-11 / USE-01: append-only metering per company, employee and conversation."""

    employee = models.ForeignKey(AIEmployee, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    meter = models.CharField(max_length=30, help_text="ai_input_tokens, ai_output_tokens, ai_credits, embedding_tokens")
    quantity = models.FloatField()
    unit = models.CharField(max_length=20, default="tokens")
    task = models.CharField(max_length=30, blank=True)
    provider_key = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=200, blank=True)
    provider_cost_paise = models.FloatField(default=0)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["company", "meter", "occurred_at"])]
