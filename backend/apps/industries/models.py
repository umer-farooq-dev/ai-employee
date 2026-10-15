"""Industry template engine (M04: IND-01 … IND-06, SA-05, SA-07).

An industry has versioned templates. A template version holds everything an AI Employee and the CRM need for that
industry: instructions, qualification flow, CRM fields, catalogue types and fields, appointment types, lead statuses,
scoring rules, handoff rules, greetings, disclosure texts, default WhatsApp templates and FAQs. Companies stay on
their version until they accept an update. Nothing here is code: all rows are data edited in Super Admin.
"""

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Industry(BaseModel):
    """IND-01. Active industries show on the website, in registration and (Phase 4) in the AI Employee wizard."""

    key = models.SlugField(max_length=50, unique=True, help_text="Also the website URL: /industries/<key>/")
    name = models.CharField(max_length=100)
    short_description = models.CharField(max_length=255, blank=True, help_text="Card text on the website")
    description = models.TextField(blank=True, help_text="Industry page body (HTML allowed)")
    icon = models.CharField(max_length=500, blank=True, help_text="Image URL")
    image = models.CharField(max_length=500, blank=True, help_text="Image URL for the industry page")
    supported_languages = models.JSONField(default=list, blank=True, help_text="Language codes, e.g. en, hi, bn")
    is_active = models.BooleanField(
        default=False, help_text="Active industries show on the website and in registration"
    )
    sort_order = models.PositiveIntegerField(default=0)
    published_version = models.ForeignKey(
        "industries.TemplateVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "industries"

    def __str__(self):
        return self.name


class TemplateVersion(BaseModel):
    """IND-02 / IND-03: one version of an industry template. Only drafts can be edited."""

    DRAFT, PUBLISHED, ARCHIVED = "draft", "published", "archived"
    STATUSES = [(DRAFT, "Draft"), (PUBLISHED, "Published"), (ARCHIVED, "Archived")]

    industry = models.ForeignKey(Industry, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUSES, default=DRAFT, db_index=True)
    notes = models.TextField(blank=True, help_text="What changed in this version")
    base_instructions = models.TextField(blank=True, help_text="AI persona guidelines and base instructions")
    qualification_flow = models.JSONField(default=list, blank=True, help_text="Ordered questions mapped to CRM fields")
    handoff_rules = models.JSONField(default=list, blank=True, help_text="When the AI hands over to a human")
    greetings = models.JSONField(default=dict, blank=True, help_text="{language: greeting}")
    disclosure_texts = models.JSONField(default=dict, blank=True, help_text="{language: AI-disclosure text}")
    default_faqs = models.JSONField(default=list, blank=True)
    whatsapp_templates = models.JSONField(default=list, blank=True, help_text="Default WhatsApp templates")
    enabled_tools = models.JSONField(default=list, blank=True, help_text="Tool keys (tool registry in Phase 4)")
    status_transitions = models.JSONField(
        default=dict, blank=True, help_text="{event: lead status key}, e.g. appointment_booked → appointment"
    )
    score_thresholds = models.JSONField(default=dict, blank=True, help_text="{hot: 70, warm: 40}")
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["industry", "-version"]
        constraints = [models.UniqueConstraint(fields=["industry", "version"], name="uniq_template_version")]

    def __str__(self):
        return f"{self.industry.name} v{self.version}"

    @property
    def editable(self):
        return self.status == self.DRAFT


class TemplateChild(BaseModel):
    """Rows owned by a template version (platform) or by one company (tenant). Protected by RLS: a company sees
    platform rows and its own rows only, and can never write platform rows."""

    template_version = models.ForeignKey(TemplateVersion, null=True, blank=True, on_delete=models.CASCADE)
    company = models.ForeignKey("tenancy.Company", null=True, blank=True, on_delete=models.CASCADE)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["sort_order", "created_at"]


class FieldDefinition(TemplateChild):
    """CRM-04 / CAT-01: one dynamic field for leads or a catalogue type. Same engine for both."""

    TYPES = [
        ("text", "Text"),
        ("textarea", "Long text"),
        ("number", "Number"),
        ("currency", "Currency (INR)"),
        ("date", "Date"),
        ("datetime", "Date & time"),
        ("single_select", "Single select"),
        ("multi_select", "Multi select"),
        ("yes_no", "Yes / No"),
        ("phone", "Phone"),
        ("email", "Email"),
        ("location", "Location"),
        ("file", "File"),
    ]

    entity = models.CharField(max_length=60, help_text="lead, or catalog:<catalogue type key>")
    key = models.SlugField(max_length=60)
    label = models.CharField(max_length=120)
    type = models.CharField(max_length=20, choices=TYPES, default="text")
    options = models.JSONField(default=list, blank=True, help_text="Choices for select fields")
    required = models.BooleanField(default=False)
    ai_extractable = models.BooleanField(default=False, help_text="The AI fills this field from conversations")
    extraction_hint = models.CharField(max_length=255, blank=True)
    filterable = models.BooleanField(default=False)
    show_in_list = models.BooleanField(default=False)
    help_text = models.CharField(max_length=255, blank=True)
    validation = models.JSONField(default=dict, blank=True, help_text="{min, max, max_length}")
    is_active = models.BooleanField(default=True)

    class Meta(TemplateChild.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["template_version", "entity", "key"],
                name="uniq_field_template",
                condition=models.Q(company__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["company", "entity", "key"],
                name="uniq_field_company",
                condition=models.Q(company__isnull=False),
            ),
        ]

    def __str__(self):
        return f"{self.entity}.{self.key}"


class CatalogType(TemplateChild):
    """CAT-01: a kind of catalogue for an industry (property, travel package, course …)."""

    key = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    item_label = models.CharField(max_length=60, blank=True, help_text="One item, e.g. Property")
    match_rules = models.JSONField(default=dict, blank=True, help_text="Used by AI matching (Phase 4)")
    display = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name

    @property
    def entity(self):
        return f"catalog:{self.key}"


class AppointmentType(TemplateChild):
    """CAL-04: Site Visit, Counselling Session, Travel Consultation …"""

    LOCATION_MODES = [("in_person", "In person"), ("phone", "Phone"), ("video", "Video call")]

    key = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    duration_min = models.PositiveIntegerField(default=30)
    buffer_min = models.PositiveIntegerField(default=0)
    location_mode = models.CharField(max_length=20, choices=LOCATION_MODES, default="in_person")
    reminder_offsets = models.JSONField(default=list, blank=True, help_text="Minutes before, e.g. [1440, 120]")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class LeadStatus(TemplateChild):
    """CRM-02. Platform defaults have neither a template nor a company; a template may define its own set."""

    OPEN, WON, LOST = "open", "won", "lost"
    CATEGORIES = [(OPEN, "Open"), (WON, "Won"), (LOST, "Lost")]

    key = models.SlugField(max_length=40)
    label = models.CharField(max_length=60)
    color = models.CharField(max_length=7, default="#6c757d")
    category = models.CharField(max_length=10, choices=CATEGORIES, default=OPEN)
    is_system = models.BooleanField(default=False)

    class Meta(TemplateChild.Meta):
        verbose_name_plural = "lead statuses"

    def __str__(self):
        return self.label


class LeadSource(BaseModel):
    """CRM-03: platform list managed in Super Admin."""

    key = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "label"]

    def __str__(self):
        return self.label


class ScoringRule(TemplateChild):
    """SCORE-02: condition → points (or a forced label). A company rule with the same key replaces the template rule."""

    key = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    condition = models.JSONField(default=dict, help_text='{"field": "custom.budget", "op": "present"} or {"event": …}')
    points = models.IntegerField(default=0)
    force_label = models.CharField(
        max_length=10, blank=True, choices=[("", "—"), ("hot", "Hot"), ("warm", "Warm"), ("cold", "Cold")]
    )
    priority = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Holiday(BaseModel):
    """CAL-09: platform holidays set by Super Admin (company holidays live on the company)."""

    date = models.DateField()
    name = models.CharField(max_length=100)
    region = models.CharField(max_length=100, blank=True, help_text="Empty = all of India")

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["date", "region"], name="uniq_platform_holiday")]

    def __str__(self):
        return f"{self.date} {self.name}"
