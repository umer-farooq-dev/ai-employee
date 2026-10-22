from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.tenancy.models import TenantModel

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
    flags = models.JSONField(default=dict, blank=True, help_text="SA-20 {feature: true|false}; missing = on")
    gateway_plans = models.JSONField(default=dict, blank=True, help_text="Payment gateway plan ids per price")
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


# SA-20 feature flags: what a plan (or one company) may use. Labels only; on/off is data in Super Admin.
# A flag missing on a plan means "on", so plans saved before a flag existed keep everything.
FEATURES = [
    ("voice_calls", "Voice calls (inbound and outbound)"),
    ("recordings", "Call recordings"),
    ("whatsapp", "WhatsApp"),
    ("web_chat", "Website chat widget"),
    ("campaigns", "Outbound calling campaigns"),
    ("calendar", "Calendar and appointments"),
    ("knowledge", "Knowledge base"),
    ("catalog", "Catalogue"),
    ("lead_import", "Lead import and export"),
    ("analytics", "Dashboard analytics"),
    ("api_access", "API and mobile app access"),
]
INTERVALS = [("monthly", "Monthly"), ("yearly", "Yearly")]


class Subscription(TenantModel):
    """SUB-03 / SUB-04: the company's billing state. The plan itself is Company.plan (what every limit reads)."""

    TRIALING, PENDING, ACTIVE, PAST_DUE, CANCELLED = "trialing", "pending", "active", "past_due", "cancelled"
    STATUSES = [
        (TRIALING, "Free trial"),
        (PENDING, "Waiting for the first payment"),
        (ACTIVE, "Active"),
        (PAST_DUE, "Payment overdue"),
        (CANCELLED, "Cancelled"),
    ]
    RAZORPAY, MANUAL = "razorpay", "manual"

    interval = models.CharField(max_length=10, choices=INTERVALS, default="monthly")
    status = models.CharField(max_length=10, choices=STATUSES, default=TRIALING, db_index=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True, db_index=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=300, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    pending_plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    pending_interval = models.CharField(max_length=10, choices=INTERVALS, blank=True)
    grace_until = models.DateTimeField(null=True, blank=True, help_text="Overdue: full access until then")
    failed_payments = models.PositiveSmallIntegerField(default=0)
    last_payment_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True, help_text="Last trial / renewal reminder")
    gateway = models.CharField(max_length=20, default=RAZORPAY, help_text="razorpay / manual")
    gateway_subscription_id = models.CharField(max_length=60, blank=True, db_index=True)
    gateway_customer_id = models.CharField(max_length=60, blank=True)
    # SUB-04 enterprise: set by Super Admin for this company only
    custom_price_paise = models.BigIntegerField(null=True, blank=True, help_text="Price per interval, before GST")
    custom_limits = models.JSONField(
        default=dict, blank=True, help_text='{key: {"limit": n|null, "enforcement": "hard"|"soft", "overage": paise}}'
    )
    feature_overrides = models.JSONField(default=dict, blank=True, help_text="{feature: true|false}")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company"], name="uniq_subscription_company")]

    @property
    def manual(self):
        return self.gateway == self.MANUAL


class InvoiceSequence(BaseModel):
    """GST rule: one consecutive series per financial year. Platform table, locked row per number."""

    key = models.CharField(max_length=30, unique=True)
    last = models.PositiveIntegerField(default=0)


class Invoice(TenantModel):
    """SUB-06: GST tax invoice. Seller and buyer details are copied at issue time so the PDF never changes."""

    DUE, PAID, VOID = "due", "paid", "void"
    STATUSES = [(DUE, "Due"), (PAID, "Paid"), (VOID, "Cancelled")]
    KINDS = [
        ("subscription", "Subscription"),
        ("upgrade", "Plan upgrade (prorated)"),
        ("manual", "Manual invoice"),
    ]

    number = models.CharField(max_length=16, unique=True)
    kind = models.CharField(max_length=15, choices=KINDS, default="subscription")
    status = models.CharField(max_length=5, choices=STATUSES, default=DUE, db_index=True)
    issued_at = models.DateTimeField()
    due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    interval = models.CharField(max_length=10, blank=True)
    seller = models.JSONField(default=dict)
    buyer = models.JSONField(default=dict)
    place_of_supply = models.CharField(max_length=60, blank=True, help_text="State (code)")
    intra_state = models.BooleanField(default=True)
    lines = models.JSONField(default=list, help_text="[{description, sac, quantity, unit_paise, amount_paise}]")
    subtotal_paise = models.BigIntegerField(default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_paise = models.BigIntegerField(default=0)
    sgst_paise = models.BigIntegerField(default=0)
    igst_paise = models.BigIntegerField(default=0)
    total_paise = models.BigIntegerField(default=0)
    notes = models.TextField(blank=True)
    payment_ref = models.CharField(max_length=120, blank=True, help_text="Gateway payment id / bank reference")

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return self.number

    @property
    def tax_paise(self):
        return self.cgst_paise + self.sgst_paise + self.igst_paise


class Payment(TenantModel):
    """Billing history (USE-02, SA-13): every attempt, failed ones included."""

    CREATED, CAPTURED, FAILED, REFUNDED = "created", "captured", "failed", "refunded"
    STATUSES = [(CREATED, "Started"), (CAPTURED, "Paid"), (FAILED, "Failed"), (REFUNDED, "Refunded")]

    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=10, choices=STATUSES, default=CREATED, db_index=True)
    purpose = models.CharField(max_length=20, default="subscription", help_text="subscription / upgrade / invoice")
    gateway = models.CharField(max_length=20, default="razorpay")
    gateway_payment_id = models.CharField(max_length=60, blank=True, db_index=True)
    gateway_order_id = models.CharField(max_length=60, blank=True, db_index=True)
    method = models.CharField(max_length=30, blank=True)
    error = models.CharField(max_length=300, blank=True)
    data = models.JSONField(default=dict, blank=True, help_text="What the payment is for (plan, interval …)")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]


class CreditAdjustment(TenantModel):
    """USE-04: AI credits given (+) or taken back (-) by Super Admin. They count in the month they are given."""

    credits = models.IntegerField()
    reason = models.CharField(max_length=300)
    month = models.DateField(help_text="First day of the month the credits apply to")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
