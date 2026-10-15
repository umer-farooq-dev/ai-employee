from django.db import models

from apps.core.models import BaseModel

# Limits a plan can set (SUB-01). Labels only; values are data entered in Super Admin.
ENTITLEMENTS = [
    ("ai_employees", "AI Employees"),
    ("users", "Users / seats"),
    ("voice_minutes", "Voice minutes / month"),
    ("calls", "Calls / month"),
    ("whatsapp_conversations", "WhatsApp conversations / month"),
    ("ai_credits", "AI credits / month"),
    ("kb_storage_mb", "Knowledge storage (MB)"),
    ("kb_sources", "Knowledge sources"),
    ("concurrent_calls", "Concurrent calls"),
    ("campaigns", "Active campaigns"),
    ("custom_fields", "Company custom CRM fields"),
]


class Plan(BaseModel):
    ACTIVE, ARCHIVED = "active", "archived"

    key = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price_monthly_paise = models.BigIntegerField(null=True, blank=True, help_text="Empty = custom / on request")
    price_yearly_paise = models.BigIntegerField(null=True, blank=True)
    gst_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Empty = platform GST rate"
    )
    trial_days = models.PositiveIntegerField(null=True, blank=True, help_text="Empty = platform trial setting")
    is_public = models.BooleanField(default=True, help_text="Shown on the website pricing section")
    is_custom = models.BooleanField(default=False, help_text="Enterprise / custom plan")
    features = models.JSONField(default=list, blank=True, help_text="Feature bullet points for the pricing page")
    status = models.CharField(max_length=20, choices=[(ACTIVE, "Active"), (ARCHIVED, "Archived")], default=ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def price_monthly_inr(self):
        return None if self.price_monthly_paise is None else self.price_monthly_paise / 100


class PlanEntitlement(BaseModel):
    HARD, SOFT = "hard", "soft"

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="entitlements")
    key = models.CharField(max_length=50, choices=ENTITLEMENTS)
    limit_value = models.BigIntegerField(null=True, blank=True, help_text="Empty = not set / unlimited")
    overage_price_paise = models.BigIntegerField(null=True, blank=True)
    enforcement = models.CharField(max_length=10, choices=[(HARD, "Hard stop"), (SOFT, "Allow overage")], default=HARD)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan", "key"], name="uniq_plan_entitlement")]
