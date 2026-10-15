"""ROLE-01: AI Employee role templates (Sales Executive, Receptionist …). The tool registry joins in Phase 4."""

from django.db import models

from apps.core.models import BaseModel

CHANNELS = [
    ("inbound_voice", "Inbound voice"),
    ("outbound_voice", "Outbound voice"),
    ("whatsapp", "WhatsApp"),
    ("web_chat", "Website chat"),
]


class EmployeeRole(BaseModel):
    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=500, blank=True, help_text="Image URL")
    instructions = models.TextField(blank=True, help_text="Role instructions added to the industry instructions")
    allowed_channels = models.JSONField(default=list, blank=True)
    allowed_tools = models.JSONField(default=list, blank=True, help_text="Tool keys (tool registry in Phase 4)")
    default_rules = models.JSONField(default=dict, blank=True)
    plan_keys = models.JSONField(default=list, blank=True, help_text="Plans that may use this role; empty = all plans")
    industries = models.ManyToManyField("industries.Industry", blank=True, help_text="Empty = every industry")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name
