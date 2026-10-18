"""ROLE-01: AI Employee role templates (Sales Executive, Receptionist …) and the tool registry (TOOL-01, SA-06)."""

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
    allowed_tools = models.JSONField(default=list, blank=True, help_text="Tool keys from Super Admin → AI Tools")
    default_rules = models.JSONField(default=dict, blank=True)
    plan_keys = models.JSONField(default=list, blank=True, help_text="Plans that may use this role; empty = all plans")
    industries = models.ManyToManyField("industries.Industry", blank=True, help_text="Empty = every industry")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Tool(BaseModel):
    """TOOL-01: an action the AI may call. `handler` is the server code that runs it (apps.agents.tools.HANDLERS);
    `config` binds a generic handler to data — e.g. search_property = catalog search on the "property" catalogue —
    so industry-specific tools are configuration, not code."""

    CATEGORIES = [
        ("crm", "CRM"),
        ("catalog", "Catalogue"),
        ("calendar", "Calendar"),
        ("communication", "Communication"),
        ("industry", "Industry"),
    ]
    SIDE_EFFECTS = [("read", "Read only"), ("write", "Writes data"), ("external", "Sends outside")]

    key = models.SlugField(max_length=60, unique=True, help_text="Name the AI sees, e.g. search_property")
    name = models.CharField(max_length=120)
    description = models.TextField(help_text="Told to the AI: when and why to use this tool")
    category = models.CharField(max_length=20, choices=CATEGORIES, default="crm")
    handler = models.CharField(max_length=60, help_text="Server handler that runs the tool")
    config = models.JSONField(default=dict, blank=True, help_text='Handler settings, e.g. {"catalog_type": "property"}')
    input_schema = models.JSONField(
        default=dict, blank=True, help_text="Extra JSON-schema properties; catalogue tools add their filters itself"
    )
    side_effect = models.CharField(max_length=10, choices=SIDE_EFFECTS, default="read")
    timeout_ms = models.PositiveIntegerField(default=10000)
    industries = models.ManyToManyField("industries.Industry", blank=True, help_text="Empty = every industry")
    role_keys = models.JSONField(default=list, blank=True, help_text="Employee role keys; empty = every role")
    is_active = models.BooleanField(default=True, help_text="Off = disabled platform-wide (TOOL-13)")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["category", "sort_order", "key"]

    def __str__(self):
        return self.key
