"""M14 Voice AI: phone numbers, calls (state machine), handoffs and telephony webhook de-duplication (SDD §9, §11)."""

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.tenancy.models import TenantModel


class PhoneNumber(BaseModel):
    """VOICE-16: a number of a telephony provider. Platform pool row; Super Admin gives it to a company, the company
    connects it to one AI Employee (inbound routing). Test numbers belong to our development account."""

    ACTIVE, INACTIVE = "active", "inactive"
    CAPABILITIES = [("inbound", "Inbound calls"), ("outbound", "Outbound calls")]

    provider = models.ForeignKey("providers.Provider", on_delete=models.PROTECT, related_name="phone_numbers")
    e164 = models.CharField(max_length=16, unique=True)
    label = models.CharField(max_length=80, blank=True)
    provider_number_id = models.CharField(max_length=120, blank=True, help_text="Id at the provider (if any)")
    capabilities = models.JSONField(default=list, blank=True)
    company = models.ForeignKey(
        "tenancy.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="phone_numbers"
    )
    employee = models.ForeignKey(
        "agents.AIEmployee", null=True, blank=True, on_delete=models.SET_NULL, related_name="phone_numbers"
    )
    is_test = models.BooleanField(default=False, help_text="Our development account (switched at launch)")
    status = models.CharField(max_length=10, default=ACTIVE, choices=[(ACTIVE, "Active"), (INACTIVE, "Inactive")])

    class Meta:
        ordering = ["e164"]

    def __str__(self):
        return self.e164


class Call(TenantModel):
    """REC-01 per-call record and the SDD §9.6 state machine."""

    QUEUED, RINGING, IN_PROGRESS = "queued", "ringing", "in_progress"
    TRANSFERRING, TRANSFERRED, VOICEMAIL = "transferring", "transferred", "voicemail"
    COMPLETED, BUSY, NO_ANSWER, FAILED, CANCELED = "completed", "busy", "no_answer", "failed", "canceled"
    STATUSES = [
        (QUEUED, "Queued"),
        (RINGING, "Ringing"),
        (IN_PROGRESS, "In progress"),
        (TRANSFERRING, "Transferring"),
        (TRANSFERRED, "Transferred"),
        (VOICEMAIL, "Voicemail"),
        (COMPLETED, "Completed"),
        (BUSY, "Busy"),
        (NO_ANSWER, "No answer"),
        (FAILED, "Failed"),
        (CANCELED, "Canceled"),
    ]
    TERMINAL = {VOICEMAIL, COMPLETED, BUSY, NO_ANSWER, FAILED, CANCELED}
    LIVE = {RINGING, IN_PROGRESS, TRANSFERRING, TRANSFERRED}
    TRANSITIONS = {
        QUEUED: {RINGING, IN_PROGRESS, FAILED, CANCELED, BUSY, NO_ANSWER},
        RINGING: {IN_PROGRESS, BUSY, NO_ANSWER, FAILED, CANCELED, VOICEMAIL},
        IN_PROGRESS: {TRANSFERRING, COMPLETED, FAILED, VOICEMAIL},
        TRANSFERRING: {TRANSFERRED, IN_PROGRESS, COMPLETED, FAILED},
        TRANSFERRED: {COMPLETED, FAILED},
    }
    REASONS = [
        ("inbound", "Inbound call"),
        ("call_now", "Call now"),
        ("follow_up", "Scheduled follow-up"),
        ("retry", "Retry"),
        ("campaign", "Campaign"),
        ("campaign_test", "Campaign test"),
        ("browser_test", "Browser test"),
        ("test_call", "Test call to own phone"),
    ]
    TEST_REASONS = ("browser_test", "test_call", "campaign_test")  # test data is removed, never retried
    TRANSFER = [
        ("none", "No transfer"),
        ("requested", "Requested"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("no_agent", "No agent available"),
    ]
    RECORDING = [
        ("none", "Not recorded"),
        ("recording", "Recording"),
        ("stored", "Stored"),
        ("deleted", "Deleted (retention)"),
        ("failed", "Failed"),
    ]

    employee = models.ForeignKey("agents.AIEmployee", on_delete=models.CASCADE, related_name="calls")
    conversation = models.OneToOneField(
        "agents.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="call"
    )
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    phone_number = models.ForeignKey(PhoneNumber, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    provider = models.ForeignKey(
        "providers.Provider", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider_call_id = models.CharField(max_length=120, blank=True, db_index=True)
    direction = models.CharField(
        max_length=10, default="inbound", choices=[("inbound", "Inbound"), ("outbound", "Outbound")]
    )
    reason = models.CharField(max_length=20, choices=REASONS, default="inbound")
    from_e164 = models.CharField(max_length=16, blank=True)
    to_e164 = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=15, choices=STATUSES, default=QUEUED, db_index=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    retry_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="retries")
    campaign_member = models.ForeignKey(
        "campaigns.CampaignMember", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls"
    )
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Queued call: dial at")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    queued_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_sec = models.PositiveIntegerField(default=0)
    billable_sec = models.PositiveIntegerField(default=0)
    hangup_by = models.CharField(max_length=10, blank=True, help_text="customer / ai / agent / system")
    amd_result = models.CharField(max_length=10, blank=True, help_text="human / machine / unknown")
    language = models.CharField(max_length=10, blank=True)
    transfer_status = models.CharField(max_length=10, choices=TRANSFER, default="none")
    recording_key = models.CharField(max_length=500, blank=True)
    recording_status = models.CharField(max_length=10, choices=RECORDING, default="none")
    recording_seconds = models.PositiveIntegerField(default=0)
    # VOICE-22: {"turns": [{"stt_ms", "llm_ms", "tts_ms", "total_ms"}], "p50_ms", "p95_ms", "interruptions",
    # "silences", "errors": [...], "stt_confidence": avg, "providers": {"stt": key, "tts": key}}
    metrics = models.JSONField(default=dict, blank=True)
    events = models.JSONField(default=list, blank=True, help_text="[{at, status, detail}] status history")
    error = models.CharField(max_length=500, blank=True)
    cost_paise = models.FloatField(default=0, help_text="Telephony + speech provider cost")

    class Meta:
        ordering = ["-queued_at"]
        indexes = [
            models.Index(fields=["company", "-queued_at"]),
            models.Index(fields=["company", "status"]),
        ]

    def __str__(self):
        return f"{self.direction} {self.to_e164 if self.direction == 'outbound' else self.from_e164}"

    @property
    def customer_number(self):
        return self.to_e164 if self.direction == "outbound" else self.from_e164


class Handoff(TenantModel):
    """HO-01 … HO-05: the AI hands a live conversation to a person — why, who was tried, how fast, the outcome."""

    PENDING, RINGING, ACCEPTED, MISSED, NO_AGENT, COMPLETED, FAILED = (
        "pending",
        "ringing",
        "accepted",
        "missed",
        "no_agent",
        "completed",
        "failed",
    )
    STATUSES = [
        (PENDING, "Waiting for an agent"),
        (RINGING, "Ringing the agent"),
        (ACCEPTED, "Agent joined"),
        (MISSED, "Agent did not answer"),
        (NO_AGENT, "No agent available"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    ]
    REASONS = [
        ("customer_request", "Customer asked for a person"),
        ("knowledge_gap", "Question outside approved knowledge"),
        ("hot_lead", "Hot lead"),
        ("keyword", "Keyword said"),
        ("repeated_failure", "AI did not understand repeatedly"),
        ("negative_sentiment", "Customer upset"),
        ("ai_decision", "AI escalated"),
    ]

    conversation = models.ForeignKey("agents.Conversation", on_delete=models.CASCADE, related_name="handoffs")
    call = models.ForeignKey(Call, null=True, blank=True, on_delete=models.SET_NULL, related_name="handoffs")
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="handoffs")
    channel = models.CharField(max_length=10, default="voice")
    mode = models.CharField(max_length=5, default="warm", help_text="warm (agent hears a summary first) / cold")
    reason = models.CharField(max_length=20, choices=REASONS, default="customer_request")
    detail = models.CharField(max_length=300, blank=True)
    summary = models.TextField(blank=True, help_text="HO-03 what the agent sees / hears at the moment of transfer")
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="handoffs"
    )
    tried_user_ids = models.JSONField(default=list, blank=True)
    candidates = models.JSONField(default=list, blank=True, help_text="Agents in routing order (user ids)")
    accepted_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    seen_at = models.DateTimeField(null=True, blank=True, help_text="Screen pop shown to the agent")
    callback_task = models.ForeignKey("crm.Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "assigned_user", "status"])]

    @property
    def seconds_to_answer(self):
        return int((self.accepted_at - self.created_at).total_seconds()) if self.accepted_at else None


class WebhookEvent(BaseModel):
    """SEC-13: every verified provider callback once (retries from the provider are ignored)."""

    provider_key = models.CharField(max_length=60)
    event_key = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
