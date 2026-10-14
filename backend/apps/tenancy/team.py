"""Team management (AUTH-07): invitations, roles, deactivation, ownership transfer, plan seat limit.

Every function takes the company explicitly; callers get it from request.company (never from user input).
"""

import hashlib
import secrets
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.services import record
from apps.notifications import services as mail
from apps.platform_config import services as config
from apps.rbac.models import Role

from .context import platform_context
from .models import Invitation, Membership

OWNER = "owner"


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def seat_limit(company):
    """Users / seats from the company's plan (None = not limited)."""
    if not company.plan_id:
        return None
    row = company.plan.entitlements.filter(key="users").first()
    return row.limit_value if row else None


def seats_used(company):
    with platform_context():
        members = Membership.all_companies.filter(company=company, status=Membership.ACTIVE).count()
        invites = Invitation.all_companies.filter(
            company=company, status=Invitation.PENDING, expires_at__gt=timezone.now()
        ).count()
    return members + invites


def _check_seat(company):
    limit = seat_limit(company)
    if limit is not None and seats_used(company) >= limit:
        raise ValidationError(f"Your plan allows {limit} users. Upgrade the plan or remove a user first.")


def company_roles():
    return Role.objects.filter(scope="company").exclude(key=OWNER)


def _company_role(role):
    if role.scope != "company" or role.key == OWNER:
        raise ValidationError("Choose a team role. Ownership is changed with “Transfer ownership”.")


def _send_invitation(invitation, token, request):
    url = reverse("panel:accept_invitation", args=[token])
    mail.send(
        "team/invitation",
        invitation.email,
        {
            "company": invitation.company,
            "inviter": invitation.invited_by,
            "role": invitation.role,
            "accept_url": request.build_absolute_uri(url) if request else url,
            "expires_at": invitation.expires_at,
        },
    )


def _new_token(invitation):
    token = secrets.token_urlsafe(32)
    invitation.token_hash = _hash(token)
    invitation.expires_at = timezone.now() + timedelta(days=config.get("team.invite_valid_days"))
    return token


@transaction.atomic
def invite(company, email, role, invited_by, request=None) -> Invitation:
    email = email.lower().strip()
    _company_role(role)
    with platform_context():
        if Membership.all_companies.filter(company=company, user__email=email).exists():
            raise ValidationError("This person is already in your team.")
        if Invitation.all_companies.filter(
            company=company, email=email, status=Invitation.PENDING, expires_at__gt=timezone.now()
        ).exists():
            raise ValidationError("An invitation is already pending for this email. Resend it instead.")
    _check_seat(company)
    invitation = Invitation(company=company, email=email, role=role, invited_by=invited_by)
    token = _new_token(invitation)
    invitation.save()
    record(
        request, "team.invite", "invitation", invitation.id, company=company, changes={"email": email, "role": role.key}
    )
    _send_invitation(invitation, token, request)
    return invitation


def resend(invitation, request=None):
    if invitation.status != Invitation.PENDING:
        raise ValidationError("Only pending invitations can be resent.")
    if invitation.is_expired:
        _check_seat(invitation.company)
    token = _new_token(invitation)
    invitation.save(update_fields=["token_hash", "expires_at", "updated_at"])
    record(request, "team.invite_resend", "invitation", invitation.id, company=invitation.company)
    _send_invitation(invitation, token, request)
    return invitation


def cancel(invitation, request=None):
    if invitation.status != Invitation.PENDING:
        raise ValidationError("Only pending invitations can be cancelled.")
    invitation.status = Invitation.CANCELLED
    invitation.save(update_fields=["status", "updated_at"])
    record(request, "team.invite_cancel", "invitation", invitation.id, company=invitation.company)


def invitation_for_token(token):
    """Public lookup (the invitee is not signed in yet). Returns a usable invitation or raises ValidationError."""
    with platform_context():
        invitation = (
            Invitation.all_companies.select_related("company", "role").filter(token_hash=_hash(token or "")).first()
        )
    if not invitation or invitation.status != Invitation.PENDING:
        raise ValidationError("This invitation is no longer valid.")
    if invitation.is_expired:
        raise ValidationError("This invitation has expired. Ask your administrator to resend it.")
    return invitation


@transaction.atomic
def accept(invitation, user, request=None):
    """The signed-in user (with the invited email) joins the company. One company per user in the MVP."""
    if user.email.lower() != invitation.email:
        raise ValidationError(f"This invitation is for {invitation.email}. Sign in with that email.")
    with platform_context():
        if (
            Membership.all_companies.filter(user=user, status=Membership.ACTIVE)
            .exclude(company=invitation.company)
            .exists()
        ):
            raise ValidationError("This email already belongs to another company on the platform.")
        Membership.all_companies.update_or_create(
            company=invitation.company,
            user=user,
            defaults={"role": invitation.role, "status": Membership.ACTIVE, "joined_at": timezone.now()},
        )
        invitation.status = Invitation.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_at", "updated_at"])
    record(request, "team.invite_accept", "invitation", invitation.id, company=invitation.company, user=user)


@transaction.atomic
def accept_as_new_user(invitation, full_name, password, request=None):
    """Invitee without an account: the emailed link proves the address, so it is stored as verified."""
    User = get_user_model()
    if User.objects.filter(email=invitation.email).exists():
        raise ValidationError("An account with this email exists. Sign in to accept the invitation.")
    user = User.objects.create_user(invitation.email, password, full_name=full_name)
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
    accept(invitation, user, request=request)
    return user


def _owners(company):
    return Membership.all_companies.filter(company=company, role__key=OWNER, status=Membership.ACTIVE)


@transaction.atomic
def change_role(membership, role, request=None):
    _company_role(role)
    if membership.role.key == OWNER:
        raise ValidationError("Transfer ownership before changing the owner's role.")
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    record(
        request,
        "team.role_change",
        "user",
        membership.user_id,
        company=membership.company,
        changes={"role": role.key},
        category="security",
    )


@transaction.atomic
def set_member_active(membership, active, request=None):
    if not active and membership.role.key == OWNER:
        raise ValidationError("The owner cannot be deactivated. Transfer ownership first.")
    if active:
        _check_seat(membership.company)
    membership.status = Membership.ACTIVE if active else Membership.DISABLED
    membership.save(update_fields=["status", "updated_at"])
    if not active:
        from apps.accounts.services import end_sessions

        end_sessions(membership.user, request=request, audit=False)
    record(
        request,
        "team.activate" if active else "team.deactivate",
        "user",
        membership.user_id,
        company=membership.company,
        category="security",
    )


@transaction.atomic
def transfer_ownership(company, current_owner_user, new_owner_membership, previous_owner_role, request=None):
    """The current owner hands ownership to an active member and takes another team role."""
    _company_role(previous_owner_role)
    with platform_context():
        current = _owners(company).filter(user=current_owner_user).first()
    if not current:
        raise ValidationError("Only the owner can transfer ownership.")
    if new_owner_membership.company_id != company.id or new_owner_membership.status != Membership.ACTIVE:
        raise ValidationError("Choose an active member of your team.")
    if new_owner_membership.pk == current.pk:
        raise ValidationError("You are already the owner.")
    owner_role = Role.objects.get(scope="company", key=OWNER)
    new_owner_membership.role = owner_role
    new_owner_membership.save(update_fields=["role", "updated_at"])
    current.role = previous_owner_role
    current.save(update_fields=["role", "updated_at"])
    record(
        request,
        "team.transfer_ownership",
        "user",
        new_owner_membership.user_id,
        company=company,
        changes={"from": current_owner_user.email},
        category="security",
    )
