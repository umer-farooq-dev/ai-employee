from django.conf import settings
from django.db import models


class PlatformSetting(models.Model):
    """One row per registry key; the live value of a platform-wide setting."""

    key = models.CharField(max_length=100, primary_key=True)
    value = models.JSONField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key
