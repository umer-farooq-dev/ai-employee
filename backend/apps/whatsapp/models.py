"""M15 WhatsApp (WA-01 … WA-10): business numbers, message templates, the default template library and the delivery
log of every message.

Only the official WhatsApp Business Platform is used (WA-01): a provider of the "whatsapp" capability in Super Admin
(Meta Cloud API now; a BSP is another vendor with its adapter). Numbers are a platform pool like phone numbers:
Super Admin adds a number and gives it to a company, the company connects it to an AI Employee.
"""

from django.db import models

from apps.core.models import BaseModel
from apps.tenancy.models import TenantModel

CATEGORIES = [("UTILITY", "Utility"), ("MARKETING", "Marketing"), ("AUTHENTICATION", "Authentication")]
PURPOSES = [
    ("lead_follow_up", "Lead follow-up"),
    ("appointment_confirmation", "Appointment confirmation"),
    ("appointment_reminder", "Appointment reminder"),
    ("appointment_cancelled", "Appointment cancelled"),
    ("team_alert", "Alert to your team"),
    ("item_info", "Property / product information"),
    ("callback", "Callback confirmation"),
    ("general", "Other"),
]
HEADERS = [("none", "No header"), ("text", "Text"), ("image", "Image"), ("document", "Document (PDF)")]
# What a template variable {{n}} is filled with when the platform sends it.
VARIABLES = [
    ("lead.name", "Customer name"),
    ("company.name", "Company name"),
    ("employee.name", "AI Employee name"),
    ("appointment.when", "Appointment date and time"),
    ("appointment.number", "Appointment number"),
    ("appointment.type", "Appointment type"),
    ("item.title", "Property / product name"),
    ("item.price", "Property / product price"),
    ("text", "Text typed when sending"),
]


class WhatsAppNumber(BaseModel):
    """WA-02: a WhatsApp Business number of a provider (phone number id + business account id at Meta)."""

    ACTIVE, INACTIVE = "active", "inactive"

    provider = models.ForeignKey("providers.Provider", on_delete=models.PROTECT, related_name="whatsapp_numbers")
    e164 = models.CharField(max_length=16, unique=True)
    display_name = models.CharField(max_length=120, blank=True, help_text="Business name approved by Meta")
    phone_number_id = models.CharField(max_length=60, unique=True, help_text="Phone number ID at Meta")
    waba_id = models.CharField(max_length=60, help_text="WhatsApp Business Account ID (owns the templates)")
    company = models.ForeignKey(
        "tenancy.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="whatsapp_numbers"
    )
    employee = models.ForeignKey(
        "agents.AIEmployee", null=True, blank=True, on_delete=models.SET_NULL, related_name="whatsapp_numbers"
    )
    is_test = models.BooleanField(default=False, help_text="Meta test number (development)")
    status = models.CharField(max_length=10, default=ACTIVE, choices=[(ACTIVE, "Active"), (INACTIVE, "Inactive")])
    quality = models.CharField(max_length=20, blank=True, help_text="Quality rating reported by Meta")

    class Meta:
        ordering = ["e164"]

    def __str__(self):
        return self.e164


class DefaultTemplate(BaseModel):
    """Super Admin template library: companies copy one, adjust it and submit it to Meta under their account."""

    name = models.SlugField(max_length=60, unique=True, help_text="lower_case_with_underscores, as Meta needs it")
    title = models.CharField(max_length=120)
    purpose = models.CharField(max_length=30, choices=PURPOSES, default="general")
    category = models.CharField(max_length=20, choices=CATEGORIES, default="UTILITY")
    header_type = models.CharField(max_length=10, choices=HEADERS, default="none")
    # {language: {"header": str, "body": str with {{1}} …, "footer": str}}
    texts = models.JSONField(default=dict)
    variables = models.JSONField(default=list, blank=True, help_text="Source of {{1}}, {{2}} … (see VARIABLES)")
    buttons = models.JSONField(default=list, blank=True, help_text='[{"type": "QUICK_REPLY", "text": "…"}]')
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title


class Template(TenantModel):
    """WA-03: a message template of the company's WhatsApp Business Account, one row per language."""

    DRAFT, PENDING, APPROVED, REJECTED, PAUSED, DISABLED = (
        "draft",
        "pending",
        "approved",
        "rejected",
        "paused",
        "disabled",
    )
    STATUSES = [
        (DRAFT, "Draft"),
        (PENDING, "Waiting for Meta"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (PAUSED, "Paused by Meta"),
        (DISABLED, "Disabled by Meta"),
    ]

    number = models.ForeignKey(WhatsAppNumber, on_delete=models.PROTECT, related_name="templates")
    name = models.SlugField(max_length=60)
    language = models.CharField(max_length=10, help_text="Our language code")
    meta_language = models.CharField(max_length=10, help_text="Meta's language code, e.g. en, hi, bn, en_US")
    category = models.CharField(max_length=20, choices=CATEGORIES, default="UTILITY")
    purpose = models.CharField(max_length=30, choices=PURPOSES, default="general")
    header_type = models.CharField(max_length=10, choices=HEADERS, default="none")
    header_text = models.CharField(max_length=60, blank=True)
    body = models.TextField(max_length=1024)
    footer = models.CharField(max_length=60, blank=True)
    buttons = models.JSONField(default=list, blank=True)
    variables = models.JSONField(default=list, blank=True, help_text="Source of {{1}}, {{2}} … (see VARIABLES)")
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT, db_index=True)
    provider_template_id = models.CharField(max_length=60, blank=True)
    rejected_reason = models.CharField(max_length=500, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "language"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number", "name", "language"], name="uniq_wa_template")
        ]

    def __str__(self):
        return f"{self.name} ({self.language})"


class WaMessage(TenantModel):
    """WA-10: every message sent or received with its delivery status and the pricing category Meta reported."""

    QUEUED, SENT, DELIVERED, READ, FAILED, RECEIVED = "queued", "sent", "delivered", "read", "failed", "received"
    STATUSES = [
        (QUEUED, "Queued"),
        (SENT, "Sent"),
        (DELIVERED, "Delivered"),
        (READ, "Read"),
        (FAILED, "Failed"),
        (RECEIVED, "Received"),
    ]
    ORDER = {QUEUED: 0, SENT: 1, DELIVERED: 2, READ: 3}

    number = models.ForeignKey(WhatsAppNumber, on_delete=models.PROTECT, related_name="+")
    conversation = models.ForeignKey(
        "agents.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="wa_messages"
    )
    message = models.OneToOneField(
        "agents.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="wa"
    )
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    direction = models.CharField(max_length=10, choices=[("in", "Received"), ("out", "Sent")])
    wamid = models.CharField(max_length=200, blank=True, db_index=True, help_text="Message id at Meta")
    customer = models.CharField(max_length=20, help_text="Customer's WhatsApp number (E.164)")
    kind = models.CharField(max_length=20, default="text", help_text="text, template, image, document, audio …")
    template = models.ForeignKey(Template, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    error = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=20, blank=True, help_text="Pricing category reported by Meta")
    billable = models.BooleanField(null=True, blank=True)
    status_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "customer", "-created_at"])]
