from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.tenancy.models import TenantModel


class EmailTemplate(BaseModel):
    """Editable email (NOTI-01). `key` matches the sender's template name, e.g. account/email/password_reset_key."""

    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    subject = models.CharField(max_length=255)
    body_html = models.TextField(help_text="Django template syntax, e.g. {{ platform_name }}")
    variables = models.JSONField(default=list, blank=True, help_text="Variables available in this template")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Notification(TenantModel):
    """NOTI-02 / CP-03: one alert for one person — the in-app centre (bell) lists them with read / unread state;
    e-mail, WhatsApp and push copies go out on the channels the person chose (apps.notifications.alerts)."""

    KINDS = [
        ("handoff", "Transfer requests"),
        ("hot_lead", "Hot leads"),
        ("appointment", "Bookings"),
        ("campaign", "Campaigns"),
        ("usage", "Usage alerts"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=KINDS)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=500, blank=True, help_text="Panel link")
    read_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    delivery = models.JSONField(default=dict, blank=True, help_text="{channel: sent | skipped: reason | failed: error}")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return self.title


class Device(BaseModel):
    """API-05 / MOB-03: where a person receives push alerts — a browser (Web Push, installed web app) or the mobile
    app (Firebase Cloud Messaging token)."""

    PLATFORMS = [("web", "Browser / installed web app"), ("android", "Android app"), ("ios", "iPhone app")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    platform = models.CharField(max_length=10, choices=PLATFORMS)
    key = models.CharField(max_length=64, unique=True, help_text="sha256 of the token / endpoint")
    token = models.TextField(help_text="FCM token, or the Web Push endpoint URL")
    keys = models.JSONField(default=dict, blank=True, help_text="Web Push: {p256dh, auth}")
    name = models.CharField(max_length=200, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_platform_display()} · {self.name}"
