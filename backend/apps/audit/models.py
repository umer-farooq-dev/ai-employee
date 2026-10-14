import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Who did what, when, from where (SEC-08). Append-only: a database trigger blocks UPDATE and DELETE."""

    CATEGORIES = [("general", "General"), ("security", "Security")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    company = models.ForeignKey(
        "tenancy.Company", null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    actor_email = models.CharField(max_length=254, blank=True)  # kept even if the user is deleted
    impersonator_email = models.CharField(max_length=254, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORIES, default="general", db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=100, blank=True)
    entity_id = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {self.actor_email or 'system'}"


class ApiRequestLog(models.Model):
    """One row per /api/ request (SA-17 API log)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status = models.PositiveSmallIntegerField(db_index=True)
    duration_ms = models.PositiveIntegerField()
    user_email = models.CharField(max_length=254, blank=True)
    company_id = models.UUIDField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.method} {self.path} {self.status}"


class ErrorLog(models.Model):
    """Server errors captured from Django logging (SA-17 system / error log)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=20)
    logger = models.CharField(max_length=200)
    message = models.TextField()
    traceback = models.TextField(blank=True)
    path = models.CharField(max_length=500, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.level} {self.message[:80]}"
