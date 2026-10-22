from django.conf import settings
from django.db import models

from apps.core.models import BaseModel

from .context import TenantContextMissing, bypass_active, current_company_id


class TenantManager(models.Manager):
    """Default manager for company-owned data: always filtered by the current company, fails closed without one."""

    def get_queryset(self):
        qs = super().get_queryset()
        if bypass_active():
            return qs
        company_id = current_company_id()
        if company_id is None:
            raise TenantContextMissing(f"{self.model.__name__} queried without a company context")
        return qs.filter(company_id=company_id)


class TenantModel(BaseModel):
    """Base class for every company-owned table (TEN-01). Also protected by PostgreSQL row-level security."""

    company = models.ForeignKey("tenancy.Company", on_delete=models.CASCADE, db_index=True)

    objects = TenantManager()
    all_companies = models.Manager()  # platform code only, inside platform_context()

    class Meta:
        abstract = True


class Company(BaseModel):
    """A registered business (tenant root)."""

    PENDING, REJECTED = "pending", "rejected"
    TRIAL, ACTIVE, SUSPENDED, CANCELLED = "trial", "active", "suspended", "cancelled"
    STATUSES = [
        (PENDING, "Pending approval"),
        (REJECTED, "Rejected"),
        (TRIAL, "Trial"),
        (ACTIVE, "Active"),
        (SUSPENDED, "Suspended"),
        (CANCELLED, "Cancelled"),
    ]
    WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=80, unique=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=TRIAL, db_index=True)
    plan = models.ForeignKey("billing.Plan", null=True, blank=True, on_delete=models.PROTECT, related_name="companies")
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    industry = models.ForeignKey(
        "industries.Industry", null=True, blank=True, on_delete=models.PROTECT, related_name="companies"
    )
    template_version = models.ForeignKey(
        "industries.TemplateVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="companies",
        help_text="Industry template the company runs on; it changes only when the company accepts an update (IND-03)",
    )
    business_size = models.CharField(max_length=30, blank=True)
    logo = models.CharField(max_length=500, blank=True, help_text="Image URL")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=16, blank=True)
    website = models.URLField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(max_length=50, blank=True, help_text="Empty = platform default")
    default_language = models.CharField(max_length=10, blank=True, help_text="Empty = platform default")
    require_2fa = models.BooleanField(default=False, help_text="Company enforces 2FA for all its users")
    business_hours = models.JSONField(default=dict, blank=True, help_text="{mon: {open, close, closed}, …}")
    holidays = models.JSONField(default=list, blank=True, help_text="[{date, name}, …]")
    onboarding = models.JSONField(default=dict, blank=True, help_text="Completed onboarding steps {key: timestamp}")
    # Registration and approval (AUTH-01, AUTH-12)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_ip = models.GenericIPAddressField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rejected_reason = models.CharField(max_length=500, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.CharField(max_length=255, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    billing_hold = models.DateTimeField(
        null=True, blank=True, help_text="Unpaid: the AI stops and the panel opens only Billing until paid (SUB-03)"
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    @property
    def is_suspended(self):
        return self.status == self.SUSPENDED

    @property
    def awaiting_approval(self):
        """Pending or rejected: the owner can sign in but only sees the approval status page (AUTH-12)."""
        return self.status in (self.PENDING, self.REJECTED)


class Membership(TenantModel):
    """A user's place in a company, with a company-scoped role."""

    INVITED, ACTIVE, DISABLED = "invited", "active", "disabled"
    STATUSES = [(INVITED, "Invited"), (ACTIVE, "Active"), (DISABLED, "Disabled")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey("rbac.Role", on_delete=models.PROTECT, limit_choices_to={"scope": "company"})
    status = models.CharField(max_length=20, choices=STATUSES, default=ACTIVE)
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "user"], name="uniq_membership")]

    def __str__(self):
        return f"{self.user} @ {self.company_id}"


class DataRequest(TenantModel):
    """TEN-07 / COMP-09: a full data export (ZIP) or an account deletion after a grace period."""

    EXPORT, DELETION = "export", "deletion"
    KINDS = [(EXPORT, "Data export"), (DELETION, "Account deletion")]
    PENDING, READY, SCHEDULED, DONE, CANCELLED, FAILED, EXPIRED = (
        "pending",
        "ready",
        "scheduled",
        "done",
        "cancelled",
        "failed",
        "expired",
    )
    STATUSES = [
        (PENDING, "Being prepared"),
        (READY, "Ready to download"),
        (SCHEDULED, "Scheduled"),
        (DONE, "Done"),
        (CANCELLED, "Cancelled"),
        (FAILED, "Failed"),
        (EXPIRED, "Expired"),
    ]

    kind = models.CharField(max_length=10, choices=KINDS)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=500, blank=True)
    file_key = models.CharField(max_length=500, blank=True)
    file_size = models.BigIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Export: download link valid until")
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Deletion: runs at")
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Invitation(TenantModel):
    """Team invitation by email (AUTH-07). Only a hash of the token is stored; the link is emailed once."""

    PENDING, ACCEPTED, CANCELLED = "pending", "accepted", "cancelled"
    STATUSES = [(PENDING, "Pending"), (ACCEPTED, "Accepted"), (CANCELLED, "Cancelled")]

    email = models.EmailField()
    role = models.ForeignKey("rbac.Role", on_delete=models.PROTECT, limit_choices_to={"scope": "company"})
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=PENDING, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} → {self.company_id}"

    @property
    def is_expired(self):
        from django.utils import timezone

        return self.expires_at <= timezone.now()
