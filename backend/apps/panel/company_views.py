"""Company panel screens (CP-01, CP-02, CP-06, AUTH-07, AUTH-09, AUTH-10, AUTH-12 status page).

The company always comes from request.company (the signed-in user's membership), never from the URL or form data.
"""

import datetime
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts import services as accounts
from apps.industries import services as templates
from apps.rbac.models import Role
from apps.rbac.services import has_perm
from apps.tenancy import profile, team
from apps.tenancy.middleware import gate_reason
from apps.tenancy.models import Company, Invitation, Membership

from . import menu
from .forms import AcceptInvitationForm, CompanyProfileForm, InviteForm, OTPForm, TransferOwnershipForm


def company_perm(key):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.company:
                if request.user.is_staff:
                    return redirect("superadmin:dashboard")
                raise PermissionDenied
            if not has_perm(request.user, key, request.company):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _errors(request, exc):
    for message in getattr(exc, "messages", [str(exc)]):
        messages.error(request, message)


@company_perm("company.view")
def dashboard(request):
    company = request.company
    days_left = (company.trial_ends_at - timezone.now()).days if company.trial_ends_at else None
    return render(
        request,
        "panel/company/dashboard.html",
        {
            "company": company,
            "onboarding": profile.onboarding(company),
            "trial_days_left": days_left,
            "template_update": templates.update_available(company),
            "can_manage": has_perm(request.user, "company.manage", company),
            "stats": _dashboard_stats(request.user, company),
        },
    )


def _dashboard_stats(user, company):
    """A few live numbers, each shown only to people who may open the page it links to."""
    from apps.crm.models import Lead
    from apps.scheduling.models import Appointment
    from apps.voice.models import Call

    now = timezone.now()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    cards = []
    if has_perm(user, "leads.view", company):
        leads = Lead.objects.filter(company=company, deleted_at__isnull=True)
        week = leads.filter(created_at__gte=now - datetime.timedelta(days=7)).count()
        cards.append(("Leads", leads.count(), f"{week} new this week", "iconoir-group", "panel:lead_list", ""))
        hot = leads.filter(score_label=Lead.HOT).count()
        cards.append(("Hot leads", hot, "ready to close", "iconoir-fire-flame", "panel:lead_list", "?score=hot"))
    if has_perm(user, "calls.view", company):
        calls = Call.objects.filter(company=company, queued_at__gte=today).exclude(reason__in=Call.TEST_REASONS)
        answered = calls.filter(answered_at__isnull=False).count()
        cards.append(("Calls today", calls.count(), f"{answered} answered", "iconoir-phone", "panel:calls", ""))
    if has_perm(user, "calendar.view", company):
        upcoming = Appointment.objects.filter(company=company, starts_at__gte=now, status__in=Appointment.ACTIVE)
        nxt = upcoming.order_by("starts_at").first()
        hint = f"next {timezone.localtime(nxt.starts_at):%d %b %H:%M}" if nxt else "none booked"
        cards.append(("Upcoming appointments", upcoming.count(), hint, "iconoir-calendar", "panel:calendar", ""))
    return [dict(zip(("label", "value", "hint", "icon", "url", "query"), c, strict=True)) for c in cards]


@require_POST
@company_perm("company.manage")
def accept_template_update(request):
    """IND-03: the company moves to the industry's newly published template version."""
    version = templates.update_available(request.company)
    if version:
        templates.assign_version(request.company, version, request=request)
        messages.success(request, f"Your workspace now uses {version}.")
    return redirect("panel:company_home")


@login_required
def pending(request):
    """AUTH-12 / AUTH-02: the only panel page while approval or mobile verification is outstanding."""
    reason = gate_reason(request.user, request.company)
    if not reason:
        return redirect("panel:home")
    form = OTPForm(request.POST or None)
    if request.method == "POST" and reason == "phone":
        try:
            if request.POST.get("op") == "send":
                accounts.send_phone_otp(request.user, request=request)
                messages.success(request, f"A code was sent to {request.user.phone}.")
            elif form.is_valid():
                accounts.verify_phone_otp(request.user, form.cleaned_data["code"], request=request)
                messages.success(request, "Mobile number verified.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:pending")
    return render(request, "panel/company/pending.html", {"reason": reason, "company": request.company, "form": form})


@company_perm("company.view")
def coming_soon(request, key):
    item = menu.BY_KEY.get(key)
    if not item:
        raise Http404
    return render(request, "panel/company/coming_soon.html", {"label": item[1], "phase": item[6]})


@company_perm("company.view")
def company_settings(request):
    """AUTH-09 profile + CP-06 business hours and holidays."""
    company = request.company
    can_manage = has_perm(request.user, "company.manage", company)
    form = CompanyProfileForm(instance=company)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied
        op = request.POST.get("op")
        if op == "profile":
            form = CompanyProfileForm(request.POST, request.FILES, instance=Company.objects.get(pk=company.pk))
            if form.is_valid():
                profile.update_profile(company, form.cleaned_data, request=request)
                messages.success(request, "Company profile saved.")
                return redirect("panel:company_settings")
        elif op == "hours":
            hours = {
                day: {
                    "open": request.POST.get(f"{day}_open", ""),
                    "close": request.POST.get(f"{day}_close", ""),
                    "closed": bool(request.POST.get(f"{day}_closed")),
                }
                for day in Company.WEEKDAYS
            }
            holidays = [
                {"date": d, "name": n}
                for d, n in zip(
                    request.POST.getlist("holiday_date"), request.POST.getlist("holiday_name"), strict=False
                )
            ]
            try:
                profile.set_hours(company, hours, holidays, request=request)
                messages.success(request, "Business hours saved.")
            except ValidationError as exc:
                _errors(request, exc)
            return redirect("panel:company_settings")
    days = [(d, (company.business_hours or {}).get(d, {})) for d in Company.WEEKDAYS]
    return render(
        request,
        "panel/company/settings.html",
        {"form": form, "company": company, "days": days, "can_manage": can_manage},
    )


@company_perm("team.view")
def team_page(request):
    company = request.company
    can_manage = has_perm(request.user, "team.manage", company)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied
        return _team_action(request, company)
    is_owner = Membership.objects.filter(user=request.user, role__key=team.OWNER, status=Membership.ACTIVE).exists()
    return render(
        request,
        "panel/company/team.html",
        {
            "members": Membership.objects.select_related("user", "role").order_by("created_at"),
            "invitations": Invitation.objects.filter(status=Invitation.PENDING).select_related("role", "invited_by"),
            "invite_form": InviteForm(),
            "transfer_form": TransferOwnershipForm(company=company, current_user=request.user) if is_owner else None,
            "roles": team.company_roles(),
            "seat_limit": team.seat_limit(company),
            "seats_used": team.seats_used(company),
            "can_manage": can_manage,
        },
    )


def _team_action(request, company):
    op = request.POST.get("op")
    try:
        if op == "invite":
            form = InviteForm(request.POST)
            if not form.is_valid():
                raise ValidationError([e for errors in form.errors.values() for e in errors])
            team.invite(company, form.cleaned_data["email"], form.cleaned_data["role"], request.user, request=request)
            messages.success(request, f"Invitation sent to {form.cleaned_data['email']}.")
        elif op in ("resend", "cancel"):
            invitation = get_object_or_404(Invitation, pk=request.POST.get("invitation"))
            (team.resend if op == "resend" else team.cancel)(invitation, request=request)
            messages.success(request, "Invitation resent." if op == "resend" else "Invitation cancelled.")
        elif op in ("role", "deactivate", "activate"):
            membership = get_object_or_404(Membership, pk=request.POST.get("member"))
            if membership.user_id == request.user.id:
                raise ValidationError("You cannot change your own access.")
            if op == "role":
                role = get_object_or_404(Role, pk=request.POST.get("role"), scope="company")
                team.change_role(membership, role, request=request)
            else:
                team.set_member_active(membership, op == "activate", request=request)
            messages.success(request, "Team member updated.")
        elif op == "transfer":
            form = TransferOwnershipForm(request.POST, company=company, current_user=request.user)
            if not form.is_valid():
                raise ValidationError("Choose the new owner and your new role.")
            team.transfer_ownership(
                company,
                request.user,
                form.cleaned_data["new_owner"],
                form.cleaned_data["my_new_role"],
                request=request,
            )
            messages.success(request, "Ownership transferred.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("panel:team")


def accept_invitation(request, token):
    """Public link from the invitation email (AUTH-07)."""
    try:
        invitation = team.invitation_for_token(token)
    except ValidationError as exc:
        return render(request, "panel/company/invitation.html", {"error": exc.messages[0]})
    from django.contrib.auth import get_user_model

    has_account = get_user_model().objects.filter(email=invitation.email).exists()
    form = AcceptInvitationForm(request.POST or None)
    if request.method == "POST":
        try:
            if request.user.is_authenticated:
                team.accept(invitation, request.user, request=request)
            elif not has_account and form.is_valid():
                user = team.accept_as_new_user(
                    invitation, form.cleaned_data["full_name"], form.cleaned_data["password1"], request=request
                )
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            else:
                raise ValidationError([e for errors in form.errors.values() for e in errors] or ["Check the form."])
            messages.success(request, f"Welcome to {invitation.company.name}!")
            return redirect("panel:home")
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "panel/company/invitation.html",
        {"invitation": invitation, "form": form, "has_account": has_account},
    )
