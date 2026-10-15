"""Built-in calendar (M12: CAL-01 … CAL-05, CAL-08, CAL-09). Company-owned tables (TenantModel + RLS)."""

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantModel


class Resource(TenantModel):
    """CAL-02: anything bookable — a human agent, a site / project, a counsellor, a room."""

    KINDS = [("user", "Team member"), ("site", "Site / project"), ("room", "Room"), ("other", "Other")]

    kind = models.CharField(max_length=10, choices=KINDS, default="user")
    name = models.CharField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="calendar_resources"
    )
    timezone = models.CharField(max_length=50, blank=True, help_text="Empty = company timezone")
    # CAL-03 availability rules
    working_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"mon": [["09:00", "13:00"], ["14:00", "18:00"]], …}; empty = company hours',
    )
    slot_minutes = models.PositiveIntegerField(default=30)
    buffer_minutes = models.PositiveIntegerField(default=0)
    max_per_slot = models.PositiveIntegerField(default=1)
    min_notice_minutes = models.PositiveIntegerField(default=60)
    booking_window_days = models.PositiveIntegerField(default=60)
    appointment_types = models.JSONField(default=list, blank=True, help_text="Type keys; empty = all types")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AvailabilityException(TenantModel):
    """Leave, blocked time, or extra working time for one resource."""

    KINDS = [("leave", "Leave"), ("blocked", "Blocked"), ("extra", "Extra working time")]

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="exceptions")
    kind = models.CharField(max_length=10, choices=KINDS, default="leave")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["starts_at"]


class AppointmentCounter(TenantModel):
    value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company"], name="uniq_appointment_counter")]


class Appointment(TenantModel):
    """CAL-05 appointment record."""

    SCHEDULED, CONFIRMED, RESCHEDULED = "scheduled", "confirmed", "rescheduled"
    CANCELLED, COMPLETED, NO_SHOW = "cancelled", "completed", "no_show"
    STATUSES = [
        (SCHEDULED, "Scheduled"),
        (CONFIRMED, "Confirmed"),
        (RESCHEDULED, "Rescheduled"),
        (CANCELLED, "Cancelled"),
        (COMPLETED, "Completed"),
        (NO_SHOW, "No-show"),
    ]
    ACTIVE = (SCHEDULED, CONFIRMED, RESCHEDULED)
    CHANNELS = [
        ("manual", "Manual"),
        ("voice", "Phone call"),
        ("whatsapp", "WhatsApp"),
        ("web_chat", "Website chat"),
        ("api", "API"),
    ]

    number = models.PositiveIntegerField()
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="appointments")
    appointment_type = models.ForeignKey("industries.AppointmentType", on_delete=models.PROTECT, related_name="+")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="appointments")
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="appointments"
    )
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUSES, default=SCHEDULED, db_index=True)
    location = models.CharField(max_length=255, blank=True)
    meeting_link = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_by_type = models.CharField(max_length=10, default="user", help_text="user / ai")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    channel = models.CharField(max_length=10, choices=CHANNELS, default="manual")

    class Meta:
        ordering = ["starts_at"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="uniq_appointment_number")]
        indexes = [models.Index(fields=["company", "resource", "starts_at"])]

    def __str__(self):
        return f"{self.reference} {self.appointment_type.name}"

    @property
    def reference(self):
        from apps.platform_config import services as config

        return f"{config.get('calendar.appointment_prefix')}{self.number:06d}"
