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

    TRIAL, ACTIVE, SUSPENDED, CANCELLED = "trial", "active", "suspended", "cancelled"
    STATUSES = [(TRIAL, "Trial"), (ACTIVE, "Active"), (SUSPENDED, "Suspended"), (CANCELLED, "Cancelled")]

    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=80, unique=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=TRIAL, db_index=True)
    plan = models.ForeignKey("billing.Plan", null=True, blank=True, on_delete=models.PROTECT, related_name="companies")
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
    settings = models.JSONField(default=dict, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.CharField(max_length=255, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    @property
    def is_suspended(self):
        return self.status == self.SUSPENDED


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
