from django.db import models

from apps.core.models import BaseModel


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
