"""SA-19 / CP-05: support tickets from companies to the platform team, with the conversation on each ticket."""

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.tenancy.models import TenantModel


class TicketCounter(BaseModel):
    """Platform-wide ticket numbers (T-1001 …)."""

    key = models.CharField(max_length=20, unique=True)
    last = models.PositiveIntegerField(default=1000)


class Ticket(TenantModel):
    OPEN, WAITING, ANSWERED, RESOLVED, CLOSED = "open", "waiting", "answered", "resolved", "closed"
    STATUSES = [
        (OPEN, "Open"),
        (ANSWERED, "Answered"),
        (WAITING, "Waiting for support"),
        (RESOLVED, "Resolved"),
        (CLOSED, "Closed"),
    ]
    PRIORITIES = [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")]

    number = models.CharField(max_length=20, unique=True)
    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=60, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal")
    status = models.CharField(max_length=10, choices=STATUSES, default=OPEN, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="support_tickets"
    )
    last_reply_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_reply_by_staff = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_reply_at", "-created_at"]

    def __str__(self):
        return f"{self.number} {self.subject}"


class TicketMessage(TenantModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    from_staff = models.BooleanField(default=False)
    internal = models.BooleanField(default=False, help_text="Staff note, never shown to the company")
    body = models.TextField()
    attachment_key = models.CharField(max_length=500, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]
