"""Built-in CRM (M10: CRM-01 … CRM-18, SCORE-02). Every table is company-owned (TenantModel + RLS)."""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.tenancy.models import TenantModel


class LeadCounter(TenantModel):
    """Per-company lead number sequence (LD-000123)."""

    value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company"], name="uniq_lead_counter")]


class Lead(TenantModel):
    """CRM-01: common fields; industry fields live in `custom`, validated by the field engine."""

    HOT, WARM, COLD = "hot", "warm", "cold"
    SCORE_LABELS = [(HOT, "Hot"), (WARM, "Warm"), (COLD, "Cold")]
    CONSENT = [("unknown", "Unknown"), ("opted_in", "Opted in"), ("opted_out", "Opted out")]
    CREATED_VIA = [
        ("manual", "Manual"),
        ("import", "Import"),
        ("api", "API"),
        ("ai", "AI Employee"),
        ("website", "Website"),
    ]

    number = models.PositiveIntegerField()
    name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=16, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    source = models.ForeignKey("industries.LeadSource", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.ForeignKey("industries.LeadStatus", on_delete=models.PROTECT, related_name="+")
    score_label = models.CharField(max_length=10, choices=SCORE_LABELS, blank=True)
    score_value = models.PositiveSmallIntegerField(default=0)
    score_reason = models.CharField(max_length=500, blank=True)
    ai_intent_score = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="SCORE-03: last AI-assessed intent 0-100, blended with the rules"
    )
    ai_intent_reason = models.CharField(max_length=300, blank=True)
    assigned_ai_employee_id = models.UUIDField(null=True, blank=True, help_text="AI Employee handling this lead")
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_leads"
    )
    preferred_language = models.CharField(max_length=10, blank=True)
    tags = models.JSONField(default=list, blank=True)
    custom = models.JSONField(default=dict, blank=True)
    events = models.JSONField(default=list, blank=True, help_text="Events seen, e.g. appointment_booked (scoring)")
    consent_status = models.CharField(max_length=10, choices=CONSENT, default="unknown")
    dnd = models.BooleanField(default=False, help_text="Do not call")
    follow_up_at = models.DateTimeField(null=True, blank=True)
    last_contact_at = models.DateTimeField(null=True, blank=True)
    next_action = models.CharField(max_length=255, blank=True)
    created_via = models.CharField(max_length=10, choices=CREATED_VIA, default="manual")
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="uniq_lead_number"),
            models.UniqueConstraint(
                fields=["company", "phone"],
                name="uniq_lead_phone",
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(phone=""),
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "assigned_user"]),
            models.Index(fields=["company", "follow_up_at"]),
            GinIndex(fields=["custom"], name="lead_custom_gin"),
        ]

    def __str__(self):
        return f"{self.reference} {self.name}".strip()

    @property
    def reference(self):
        from apps.platform_config import services as config

        return f"{config.get('crm.lead_number_prefix')}{self.number:0{config.get('crm.lead_number_digits')}d}"


class LeadActivity(TenantModel):
    """CRM-11 timeline: every change and contact on a lead."""

    TYPES = [
        (t, t.replace("_", " ").title())
        for t in (
            "created",
            "call",
            "whatsapp",
            "chat",
            "email",
            "note",
            "status_change",
            "score_change",
            "appointment",
            "assignment",
            "handoff",
            "import",
            "merge",
            "task",
            "update",
            "follow_up",
            "consent",
        )
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    type = models.CharField(max_length=20, choices=TYPES)
    summary = models.CharField(max_length=500)
    data = models.JSONField(default=dict, blank=True)
    actor_type = models.CharField(max_length=10, default="user", help_text="user / ai / system")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]


class LeadNote(TenantModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    body = models.TextField()

    class Meta:
        ordering = ["-created_at"]


class LeadScoreEvent(TenantModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="score_events")
    label = models.CharField(max_length=10, blank=True)
    value = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(max_length=500, blank=True)
    rule_hits = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=10, default="rules", help_text="rules / ai")

    class Meta:
        ordering = ["-created_at"]


class Task(TenantModel):
    """CRM-16: follow-up tasks for humans."""

    TYPES = [("callback", "Call back"), ("follow_up", "Follow up"), ("other", "Other")]
    OPEN, DONE, CANCELLED = "open", "done", "cancelled"
    STATUSES = [(OPEN, "Open"), (DONE, "Done"), (CANCELLED, "Cancelled")]

    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_tasks"
    )
    type = models.CharField(max_length=20, choices=TYPES, default="follow_up")
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField()
    remind_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=OPEN, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by_type = models.CharField(max_length=10, default="user")

    class Meta:
        ordering = ["due_at"]


class AssignmentRule(TenantModel):
    """CRM-15: rule-based or round-robin assignment of new leads."""

    STRATEGIES = [("user", "To one person"), ("round_robin", "Round robin")]

    name = models.CharField(max_length=120)
    condition = models.JSONField(default=dict, blank=True, help_text='{"field": "location", "op": "eq", "value": …}')
    strategy = models.CharField(max_length=20, choices=STRATEGIES, default="round_robin")
    targets = models.JSONField(default=list, help_text="User ids")
    priority = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    last_index = models.IntegerField(default=-1)

    class Meta:
        ordering = ["priority", "created_at"]

    def __str__(self):
        return self.name


class ConsentRecord(TenantModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="consents")
    channel = models.CharField(max_length=20, help_text="voice / whatsapp / sms / email / all")
    action = models.CharField(max_length=10, choices=[("opt_in", "Opt in"), ("opt_out", "Opt out")])
    source = models.CharField(max_length=60, blank=True)
    evidence = models.JSONField(default=dict, blank=True)


class LeadImport(TenantModel):
    """CRM-13: one CSV / Excel import with its column mapping and error report."""

    PENDING, DONE, FAILED = "pending", "done", "failed"
    file_name = models.CharField(max_length=255)
    file_key = models.CharField(max_length=500)
    headers = models.JSONField(default=list)
    mapping = models.JSONField(default=dict, blank=True, help_text="{column: target}")
    duplicate_mode = models.CharField(max_length=10, default="skip", help_text="skip / update")
    status = models.CharField(max_length=10, default=PENDING)
    total = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True, help_text="[{row, reason}]")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]


class SavedView(TenantModel):
    """CRM-09: a named set of lead list filters for one user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_lead_views")
    name = models.CharField(max_length=80)
    params = models.CharField(max_length=2000, help_text="Query string of the lead list")

    class Meta:
        ordering = ["name"]
