"""Company lifecycle and support login. Platform code: always runs inside platform_context()."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model, login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.services import record
from apps.core.request import client_ip
from apps.notifications import services as mail
from apps.platform_config import services as config
from apps.rbac.models import Role

from .context import platform_context
from .models import Company, Membership

IMPERSONATOR_SESSION_KEY = "impersonator_id"


def unique_slug(name, exclude_id=None):
    base = slugify(name)[:70] or "company"
    slug, n = base, 1
    while Company.objects.filter(slug=slug).exclude(id=exclude_id).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


@transaction.atomic
def create_company(data: dict, owner_email: str | None = None, request=None) -> Company:
    """Create a company (Super Admin). If an owner email is given, that user becomes the company Owner."""
    company = Company.objects.create(slug=unique_slug(data["name"]), **data)
    if owner_email:
        add_member(company, owner_email, Role.objects.get(scope="company", key="owner"), request=request)
    record(request, "company.create", "company", company.id, company=company, changes={"name": company.name})
    return company


def add_member(company, email, role, request=None):
    User = get_user_model()
    user, _ = User.objects.get_or_create(email=email.lower().strip())
    with platform_context():
        membership, _ = Membership.all_companies.update_or_create(
            company=company,
            user=user,
            defaults={"role": role, "status": Membership.ACTIVE, "joined_at": timezone.now()},
        )
    record(request, "membership.add", "user", user.id, company=company, changes={"role": role.key})
    return membership


# ------------------------------------------------------------------ registration & approval (AUTH-01, AUTH-12)
def registration_plan(key=""):
    """The plan picked on the website (?plan=) if it is public and active, else the default plan setting."""
    from apps.billing.models import Plan

    plans = Plan.objects.filter(status=Plan.ACTIVE)
    return (plans.filter(key=key, is_public=True).first() if key else None) or plans.filter(
        key=config.get("registration.default_plan")
    ).first()


def _start_subscription(company):
    """Trial (days from the plan, else the platform setting) or straight to active."""
    days = company.plan.trial_days if company.plan and company.plan.trial_days is not None else None
    if days is None:
        days = config.get("registration.trial_days")
    if config.get("registration.trial_enabled") and days > 0:
        company.status = Company.TRIAL
        company.trial_ends_at = timezone.now() + timedelta(days=days)
    else:
        company.status = Company.ACTIVE
        company.trial_ends_at = None


def owners(company):
    with platform_context():
        return list(
            Membership.all_companies.filter(company=company, role__key="owner", status=Membership.ACTIVE)
            .select_related("user")
            .values_list("user__email", flat=True)
        )


@transaction.atomic
def register_company(owner, data: dict, request=None) -> Company:
    """Self-registration: company + owner membership. Waits for Super Admin approval when that setting is on."""
    company = Company(
        slug=unique_slug(data["business_name"]),
        name=data["business_name"],
        industry=data.get("industry"),
        city=data.get("city", ""),
        state=data.get("state", ""),
        business_size=data.get("business_size", ""),
        website=data.get("website", ""),
        gstin=(data.get("gstin") or "").upper(),
        email=owner.email,
        phone=owner.phone,
        plan=registration_plan(data.get("plan", "")),
        terms_accepted_at=timezone.now(),
        terms_accepted_ip=client_ip(request) if request else None,
    )
    if config.get("registration.approval_required"):
        company.status = Company.PENDING
    else:
        _start_subscription(company)
    company.save()
    add_member(company, owner.email, Role.objects.get(scope="company", key="owner"), request=request)
    record(
        request,
        "company.register",
        "company",
        company.id,
        company=company,
        user=owner,
        changes={"name": company.name, "status": company.status},
    )
    context = {
        "company": company,
        "owner": owner,
        "review_url": _absolute(request, "superadmin:company_detail", company.pk),
    }
    for to in mail.team_recipients():
        mail.send("company/registered_team", to, context)
    return company


def _absolute(request, name, *args):
    from django.urls import reverse

    path = reverse(name, args=args)
    return request.build_absolute_uri(path) if request else path


@transaction.atomic
def approve_company(company, request=None):
    if company.status not in (Company.PENDING, Company.REJECTED):
        raise ValidationError("Only pending or rejected companies can be approved.")
    _start_subscription(company)
    company.approved_at = timezone.now()
    company.approved_by = request.user if request and request.user.is_authenticated else None
    company.rejected_reason = ""
    company.save()
    record(
        request,
        "company.approve",
        "company",
        company.id,
        company=company,
        category="security",
        changes={"status": company.status},
    )
    for to in owners(company):
        mail.send("company/approved", to, {"company": company, "login_url": _absolute(request, "account_login")})
    return company


@transaction.atomic
def reject_company(company, reason, request=None):
    if company.status != Company.PENDING:
        raise ValidationError("Only pending companies can be rejected.")
    if not (reason or "").strip():
        raise ValidationError("A reason is required.")
    company.status = Company.REJECTED
    company.rejected_reason = reason.strip()
    company.save(update_fields=["status", "rejected_reason", "updated_at"])
    record(
        request,
        "company.reject",
        "company",
        company.id,
        company=company,
        category="security",
        changes={"reason": company.rejected_reason},
    )
    for to in owners(company):
        mail.send("company/rejected", to, {"company": company, "reason": company.rejected_reason})
    return company


def set_status(company, status, reason="", request=None):
    """Suspend / reactivate (TEN-06). Later phases also pause AI Employees and campaigns here."""
    if status not in dict(Company.STATUSES):
        raise ValidationError("Invalid status")
    old = company.status
    company.status = status
    company.suspended_at = timezone.now() if status == Company.SUSPENDED else None
    company.suspended_reason = reason if status == Company.SUSPENDED else ""
    company.save(update_fields=["status", "suspended_at", "suspended_reason", "updated_at"])
    record(
        request,
        f"company.{status}",
        "company",
        company.id,
        company=company,
        changes={"status": {"old": old, "new": status}, "reason": reason},
        category="security",
    )


def soft_delete(company, request=None):
    company.deleted_at = timezone.now()
    company.status = Company.CANCELLED
    company.save(update_fields=["deleted_at", "status", "updated_at"])
    record(request, "company.delete", "company", company.id, company=company, category="security")


def export_company(company, request=None) -> str:
    """JSON export of everything stored for the company so far (grows with every phase)."""
    with platform_context():
        members = list(
            Membership.all_companies.filter(company=company).values(
                "user__email", "user__full_name", "role__key", "status", "joined_at"
            )
        )
    data = {
        "company": {f.name: getattr(company, f.attname) for f in Company._meta.concrete_fields},
        "members": members,
    }
    record(request, "company.export", "company", company.id, company=company, category="security")
    return json.dumps(data, default=str, indent=2)


def start_impersonation(request, target_user, reason):
    """Support login (SA-03): staff acts as a company user. Audited, shown with a banner, reversible."""
    staff = request.user
    if target_user.is_staff or target_user.is_superuser:
        raise PermissionDenied("Staff accounts cannot be impersonated.")
    if not reason.strip():
        raise ValidationError("A reason is required.")
    record(
        request, "support.impersonate_start", "user", target_user.id, changes={"reason": reason}, category="security"
    )
    login(request, target_user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[IMPERSONATOR_SESSION_KEY] = str(staff.id)


def stop_impersonation(request):
    staff_id = request.session.get(IMPERSONATOR_SESSION_KEY)
    if not staff_id:
        return None
    impersonated = request.user
    staff = get_user_model().objects.get(id=staff_id)
    login(request, staff, backend="django.contrib.auth.backends.ModelBackend")
    record(request, "support.impersonate_stop", "user", impersonated.id, category="security", user=staff)
    return staff
