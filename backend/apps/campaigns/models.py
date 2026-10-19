from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantModel

WEEKDAYS = [
    ("mon", "Mon"),
    ("tue", "Tue"),
    ("wed", "Wed"),
    ("thu", "Thu"),
    ("fri", "Fri"),
    ("sat", "Sat"),
    ("sun", "Sun"),
]
RETRY_OUTCOMES = [("busy", "Busy"), ("no_answer", "No answer"), ("voicemail", "Voicemail"), ("failed", "Failed")]


class Campaign(TenantModel):
    """CAMP-01 / CAMP-02: planned outbound calls by one AI Employee to a lead list, within a schedule and limits."""

    DRAFT, SCHEDULED, RUNNING, PAUSED, COMPLETED, STOPPED = (
        "draft",
        "scheduled",
        "running",
        "paused",
        "completed",
        "stopped",
    )
    STATUSES = [
        (DRAFT, "Draft"),
        (SCHEDULED, "Scheduled"),
        (RUNNING, "Running"),
        (PAUSED, "Paused"),
        (COMPLETED, "Completed"),
        (STOPPED, "Stopped"),
    ]
    ACTIVE = (SCHEDULED, RUNNING, PAUSED)  # count against the plan's "active campaigns"
    SOURCES = [
        ("filter", "Lead list filter"),
        ("view", "Saved view"),
        ("csv", "CSV / Excel file"),
        ("leads", "Leads picked in the lead list"),
    ]

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    brief = models.TextField(blank=True, help_text="What the AI Employee says and offers on these calls")
    employee = models.ForeignKey("agents.AIEmployee", on_delete=models.PROTECT, related_name="campaigns")
    # lead list
    source = models.CharField(max_length=10, choices=SOURCES, default="filter")
    filter_params = models.CharField(max_length=2000, blank=True, help_text="Query string of the lead list filters")
    saved_view = models.ForeignKey("crm.SavedView", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    csv_import = models.ForeignKey("crm.LeadImport", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # schedule
    starts_on = models.DateField(null=True, blank=True, help_text="Empty = as soon as it is approved")
    ends_on = models.DateField(null=True, blank=True, help_text="Empty = until every lead is done")
    days = models.JSONField(default=list, blank=True, help_text="Weekdays to call; empty = every day")
    windows = models.JSONField(default=list, blank=True, help_text='[["10:00", "13:00"], …]; empty = calling hours')
    # retries and follow-up
    max_attempts = models.PositiveSmallIntegerField(default=3)
    retry_gap_minutes = models.PositiveIntegerField(default=120)
    retry_outcomes = models.JSONField(default=list, blank=True)
    collection = models.ForeignKey(
        "catalog.CatalogCollection", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    whatsapp_after_call = models.BooleanField(default=False)
    follow_up_labels = models.JSONField(default=list, blank=True, help_text="Score labels that get another call")
    follow_up_after_days = models.PositiveSmallIntegerField(default=2)
    # limits
    max_concurrent = models.PositiveSmallIntegerField(default=1)
    daily_limit = models.PositiveIntegerField(default=100)
    # test mode (CAMP-06)
    test_mode = models.BooleanField(default=False)
    test_numbers = models.JSONField(default=list, blank=True)
    # state
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approval_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approval_requested_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(max_length=255, blank=True)
    waiting_reason = models.CharField(max_length=255, blank=True, help_text="Why no call went out on the last run")
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def editable(self):
        return self.status in (self.DRAFT, self.SCHEDULED, self.PAUSED)


class CampaignMember(TenantModel):
    """One lead (or, in test mode, one internal number) of a campaign and what happened to it (CAMP-04 / CAMP-05)."""

    PENDING, CALLING, DONE, FAILED, SKIPPED = "pending", "calling", "done", "failed", "skipped"
    STATUSES = [
        (PENDING, "To call"),
        (CALLING, "On a call"),
        (DONE, "Done"),
        (FAILED, "Not reached"),
        (SKIPPED, "Skipped"),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="members")
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    phone = models.CharField(max_length=16)
    name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_call = models.ForeignKey("voice.Call", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_called_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=15, blank=True, help_text="Status of the last call")
    connected = models.BooleanField(default=False)
    qualified = models.BooleanField(default=False)
    hot = models.BooleanField(default=False)
    appointment = models.BooleanField(default=False)
    summary = models.TextField(blank=True)
    skip_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint(fields=["campaign", "phone"], name="uniq_campaign_phone")]
        indexes = [models.Index(fields=["campaign", "status", "next_attempt_at"])]

    def __str__(self):
        return f"{self.campaign} · {self.phone}"
