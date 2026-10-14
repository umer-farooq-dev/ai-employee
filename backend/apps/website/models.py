from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Enquiry(BaseModel):
    """Contact / Book-a-demo form on the website (WEB-06), handled in Super Admin → Platform Enquiries."""

    NEW, IN_PROGRESS, CLOSED = "new", "in_progress", "closed"
    STATUSES = [(NEW, "New"), (IN_PROGRESS, "In progress"), (CLOSED, "Closed")]

    name = models.CharField(max_length=150)
    business_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=16)
    email = models.EmailField()
    industry = models.ForeignKey("industries.Industry", null=True, blank=True, on_delete=models.SET_NULL)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=NEW, db_index=True)
    notes = models.TextField(blank=True, help_text="Internal notes")
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    source_url = models.CharField(max_length=500, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "enquiries"

    def __str__(self):
        return f"{self.business_name} ({self.email})"
