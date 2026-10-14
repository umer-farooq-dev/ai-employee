from django.db import models

from apps.core.models import BaseModel

from .catalog import COMPANY, PLATFORM


class Role(BaseModel):
    """A named set of permission keys. Platform roles are for staff; company roles are for company members."""

    scope = models.CharField(max_length=20, choices=[(PLATFORM, "Platform"), (COMPANY, "Company")])
    key = models.SlugField(max_length=50)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False, help_text="Seeded role: can be edited, not deleted.")

    class Meta:
        ordering = ["scope", "name"]
        constraints = [models.UniqueConstraint(fields=["scope", "key"], name="uniq_role_scope_key")]

    def __str__(self):
        return self.name
