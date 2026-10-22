"""Super Admin screens (SA-01 …) on the Rizz template. Views only handle HTTP; logic lives in the app services."""

from functools import wraps

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts import services as user_services
from apps.audit.models import ApiRequestLog, AuditLog, ErrorLog
from apps.audit.services import record
from apps.billing.models import Plan
from apps.cms import services as cms
from apps.cms.models import Page, Section
from apps.industries.models import Industry
from apps.notifications.models import EmailTemplate
from apps.platform_config import services as config
from apps.platform_config.registry import GROUPS
from apps.rbac.models import Role
from apps.rbac.services import has_perm
from apps.tenancy import services as tenancy
from apps.tenancy.context import platform_context
from apps.tenancy.models import Company, Membership
from apps.website import services as website
from apps.website.models import Enquiry

from . import cms_form
from .forms import (
    CompanyForm,
    EmailTemplateForm,
    EnquiryForm,
    ImpersonateForm,
    IndustryForm,
    MemberForm,
    PlanForm,
    RoleForm,
    UserForm,
    settings_form,
    settings_values,
)

User = get_user_model()
PER_PAGE = 25


def staff_perm(key):
    """Signed-in platform staff holding the permission `key` (AUTH-11 / SEC-03)."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_staff or not has_perm(request.user, key):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def page_of(request, qs):
    return Paginator(qs, PER_PAGE).get_page(request.GET.get("page"))


def _errors(request, exc):
    for message in getattr(exc, "messages", [str(exc)]):
        messages.error(request, message)


# ------------------------------------------------------------------ dashboard
@staff_perm("dashboard.view")
def dashboard(request):
    """SA-02: companies, AI Employees, calls, minutes, MRR / revenue, usage, errors, provider health."""
    from apps.billing import reports

    recent = AuditLog.objects.filter(category="security")[:8]
    return render(request, "panel/admin/dashboard.html", {"d": reports.dashboard(), "recent": recent})


# ------------------------------------------------------------------ companies (SA-03, TEN-06)
@staff_perm("companies.view")
def company_list(request):
    qs = (
        Company.objects.filter(deleted_at__isnull=True)
        .select_related("plan")
        .annotate(members=Count("membership"))
        .order_by("name")
    )
    q, status = request.GET.get("q", ""), request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(slug__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "panel/admin/companies/list.html",
        {"page": page_of(request, qs), "q": q, "status": status, "statuses": Company.STATUSES},
    )


@staff_perm("companies.manage")
def company_form(request, pk=None):
    company = get_object_or_404(Company, pk=pk) if pk else None
    form = CompanyForm(request.POST or None, instance=company)
    if request.method == "POST" and form.is_valid():
        if company:
            company = form.save()
            record(request, "company.update", "company", company.id, company=company, changes=form.changed_data)
        else:
            data = {k: v for k, v in form.cleaned_data.items() if k != "owner_email"}
            company = tenancy.create_company(data, owner_email=form.cleaned_data.get("owner_email"), request=request)
        messages.success(request, "Company saved.")
        return redirect("superadmin:company_detail", pk=company.pk)
    return render(
        request,
        "panel/admin/form.html",
        {"form": form, "title": "Edit company" if company else "New company", "back": "superadmin:company_list"},
    )


@staff_perm("companies.view")
def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)
    with platform_context():
        members = list(Membership.all_companies.filter(company=company).select_related("user", "role"))
    return render(
        request,
        "panel/admin/companies/detail.html",
        {
            "company": company,
            "members": members,
            "member_form": MemberForm(),
            "impersonate_form": ImpersonateForm(company=company),
            "audit": AuditLog.objects.filter(company=company)[:10],
            "ai_employees": _company_employees(company),
            "can_ai": has_perm(request.user, "ai_oversight.manage"),
            "can": {
                k: has_perm(request.user, f"companies.{k}")
                for k in ("manage", "suspend", "impersonate", "export", "delete", "approve")
            },
        },
    )


def _company_employees(company):
    from apps.agents.models import AIEmployee

    with platform_context():
        return list(AIEmployee.all_companies.filter(company=company).select_related("role"))


@require_POST
@staff_perm("companies.manage")
def company_add_member(request, pk):
    company = get_object_or_404(Company, pk=pk)
    form = MemberForm(request.POST)
    if form.is_valid():
        tenancy.add_member(company, form.cleaned_data["email"], form.cleaned_data["role"], request=request)
        messages.success(request, "Member added.")
    return redirect("superadmin:company_detail", pk=pk)


@require_POST
@staff_perm("companies.suspend")
def company_status(request, pk):
    company = get_object_or_404(Company, pk=pk)
    target = request.POST.get("status")
    try:
        tenancy.set_status(company, target, request.POST.get("reason", ""), request=request)
        messages.success(request, f"Company is now {company.get_status_display().lower()}.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("superadmin:company_detail", pk=pk)


@staff_perm("companies.export")
def company_export(request, pk):
    """TEN-07: the same full ZIP export the company can request (all records and files, secrets left out)."""
    from apps.tenancy.context import company_context
    from apps.tenancy.privacy import build_export

    company = get_object_or_404(Company, pk=pk)
    with company_context(company.id):
        data = build_export(company)
    record(request, "company.export", "company", company.id, company=company, category="security")
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{company.slug}-export.zip"'
    return response


@require_POST
@staff_perm("companies.delete")
def company_delete(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.POST.get("confirm") != company.slug:
        messages.error(request, "Type the company slug to confirm deletion.")
        return redirect("superadmin:company_detail", pk=pk)
    tenancy.soft_delete(company, request=request)
    from datetime import timedelta

    from django.utils import timezone

    from apps.tenancy.context import company_context
    from apps.tenancy.models import DataRequest

    with company_context(company.id):  # TEN-07: data is purged after the grace days (cron run_privacy)
        DataRequest.objects.create(
            company=company,
            kind=DataRequest.DELETION,
            status=DataRequest.SCHEDULED,
            requested_by=request.user,
            reason="Deleted by the platform team",
            scheduled_for=timezone.now() + timedelta(days=config.get("privacy.deletion_grace_days")),
        )
    messages.success(request, "Company deleted. Its data is purged after the grace days.")
    return redirect("superadmin:company_list")


@require_POST
@staff_perm("companies.impersonate")
def company_impersonate(request, pk):
    company = get_object_or_404(Company, pk=pk)
    form = ImpersonateForm(request.POST, company=company)
    if not form.is_valid():
        messages.error(request, "Choose a user and give a reason.")
        return redirect("superadmin:company_detail", pk=pk)
    try:
        tenancy.start_impersonation(request, form.cleaned_data["user"], form.cleaned_data["reason"])
    except (PermissionDenied, ValidationError) as exc:
        _errors(request, exc)
        return redirect("superadmin:company_detail", pk=pk)
    return redirect("panel:company_home")


# ------------------------------------------------------------------ users (SA-04)
@staff_perm("users.view")
def user_list(request):
    qs = User.objects.select_related("platform_role").order_by("-date_joined")
    q, kind = request.GET.get("q", ""), request.GET.get("kind", "")
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q))
    if kind == "staff":
        qs = qs.filter(is_staff=True)
    elif kind == "locked":
        qs = qs.filter(is_active=False)
    return render(request, "panel/admin/users/list.html", {"page": page_of(request, qs), "q": q, "kind": kind})


@staff_perm("users.manage")
def user_form(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            if user:
                user = form.save()
                record(request, "user.update", "user", user.id, changes=form.changed_data, category="security")
            else:
                user = user_services.create_user(
                    d["email"],
                    d["full_name"],
                    d["phone"],
                    is_staff=d["is_staff"],
                    platform_role=d["platform_role"],
                    request=request,
                )
                messages.info(request, "An email to set the password was sent to the user.")
            messages.success(request, "User saved.")
            return redirect("superadmin:user_detail", pk=user.pk)
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "panel/admin/form.html",
        {"form": form, "title": "Edit user" if user else "New user", "back": "superadmin:user_list"},
    )


@staff_perm("users.view")
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    with platform_context():
        memberships = list(Membership.all_companies.filter(user=user).select_related("company", "role"))
    return render(
        request,
        "panel/admin/users/detail.html",
        {
            "subject": user,
            "memberships": memberships,
            "has_2fa": Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists(),
            "sessions": UserSession.objects.filter(user=user).order_by("-last_seen_at"),
            "audit": AuditLog.objects.filter(Q(actor=user) | Q(entity_id=str(user.id)))[:15],
            "can_security": has_perm(request.user, "users.security"),
        },
    )


@require_POST
@staff_perm("users.security")
def user_security(request, pk, op):
    user = get_object_or_404(User, pk=pk)
    if user == request.user and op in ("lock", "reset-2fa"):
        messages.error(request, "You cannot do this to your own account.")
        return redirect("superadmin:user_detail", pk=pk)
    actions = {
        "lock": lambda: user_services.set_active(user, False, request=request),
        "unlock": lambda: user_services.set_active(user, True, request=request),
        "reset-2fa": lambda: user_services.reset_2fa(user, request=request),
        "end-sessions": lambda: user_services.end_sessions(user, request=request),
        "send-password-reset": lambda: user_services.send_password_reset(user, request),
    }
    if op not in actions:
        raise PermissionDenied
    actions[op]()
    messages.success(request, "Done.")
    return redirect("superadmin:user_detail", pk=pk)


# ------------------------------------------------------------------ roles (AUTH-11)
@staff_perm("roles.manage")
def role_list(request):
    return render(request, "panel/admin/roles/list.html", {"roles": Role.objects.all()})


@staff_perm("roles.manage")
def role_form(request, pk=None):
    role = get_object_or_404(Role, pk=pk) if pk else None
    if role is None and request.GET.get("scope"):
        role = Role(scope=request.GET["scope"])
    form = RoleForm(request.POST or None, instance=role)
    if request.method == "POST" and form.is_valid():
        role = form.save()
        record(request, "role.save", "role", role.id, changes={"permissions": role.permissions}, category="security")
        messages.success(request, "Role saved.")
        return redirect("superadmin:role_list")
    return render(request, "panel/admin/roles/form.html", {"form": form, "role": role})


@require_POST
@staff_perm("roles.manage")
def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if role.is_system or role.staff.exists() or Membership.all_companies.filter(role=role).exists():
        messages.error(request, "Seeded roles and roles in use cannot be deleted.")
    else:
        record(request, "role.delete", "role", role.id, category="security")
        role.delete()
        messages.success(request, "Role deleted.")
    return redirect("superadmin:role_list")


# ------------------------------------------------------------------ plans (SUB-01, SA-12)
@staff_perm("plans.view")
def plan_list(request):
    return render(
        request,
        "panel/admin/plans/list.html",
        {
            "plans": Plan.objects.annotate(companies_count=Count("companies")).order_by(*Plan._meta.ordering),
            "can_manage": has_perm(request.user, "plans.manage"),
        },
    )


@staff_perm("plans.manage")
def plan_form(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        record(request, "plan.save", "plan", plan.id, changes=form.changed_data)
        messages.success(request, "Plan saved.")
        return redirect("superadmin:plan_list")
    return render(request, "panel/admin/plans/form.html", {"form": form, "plan": plan})


# ------------------------------------------------------------------ settings (SA-16, SA-21 … SA-27)
def _settings_screen(request, screen, title):
    groups = [(key, label) for key, (scr, label) in GROUPS.items() if scr == screen]
    active = request.GET.get("tab") or groups[0][0]
    if active not in dict(groups):
        active = groups[0][0]
    current = config.get_all()
    form = settings_form({active}, current, request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            changed = config.update(settings_values(form), user=request.user, request=request)
            messages.success(request, f"Saved ({len(changed)} changed).")
            return redirect(f"{request.path}?tab={active}")
        except ValidationError as exc:
            _errors(request, exc)
    images = {s.key: current[s.key] for s in form.registry if s.type == "image"}
    return render(
        request,
        "panel/admin/settings.html",
        {"form": form, "groups": groups, "active": active, "title": title, "images": images},
    )


@staff_perm("settings.general")
def general_settings(request):
    return _settings_screen(request, "general", "General Settings")


@staff_perm("settings.system")
def system_settings(request):
    return _settings_screen(request, "system", "System Settings")


# ------------------------------------------------------------------ website content (WEB-04)
@staff_perm("cms.view")
def cms_pages(request):
    return render(
        request,
        "panel/admin/cms/pages.html",
        {"pages": Page.objects.annotate(section_count=Count("sections")).order_by(*Page._meta.ordering)},
    )


@staff_perm("cms.view")
def cms_page(request, pk):
    page = get_object_or_404(Page, pk=pk)
    if request.method == "POST":
        if not has_perm(request.user, "cms.manage"):
            raise PermissionDenied
        op = request.POST.get("op")
        if op == "seo":
            cms.update_seo(page, request.POST, request=request)
            messages.success(request, "SEO saved.")
        elif op in ("up", "down"):
            ids = [str(i) for i in page.sections.values_list("id", flat=True)]
            idx = ids.index(request.POST["section"])
            swap = idx - 1 if op == "up" else idx + 1
            if 0 <= swap < len(ids):
                ids[idx], ids[swap] = ids[swap], ids[idx]
                cms.reorder(page, ids, request=request)
        elif op == "visibility":
            section = get_object_or_404(Section, pk=request.POST["section"], page=page)
            cms.set_visibility(section, not section.is_visible, request=request)
        return redirect("superadmin:cms_page", pk=pk)
    return render(
        request,
        "panel/admin/cms/page.html",
        {
            "page": page,
            "sections": page.sections.select_related("section_type"),
            "can_manage": has_perm(request.user, "cms.manage"),
        },
    )


@staff_perm("cms.view")
def cms_section(request, pk):
    section = get_object_or_404(Section.objects.select_related("section_type", "page"), pk=pk)
    schema = section.section_type.schema
    if request.method == "POST":
        if not has_perm(request.user, "cms.manage"):
            raise PermissionDenied
        op = request.POST.get("op", "draft")
        try:
            if "restore" in request.POST:
                cms.restore(section, int(request.POST["restore"]), request.user, request=request)
                messages.success(request, "Older version loaded as a draft. Publish it to make it live.")
            else:
                cms.save_draft(
                    section, cms_form.parse(schema, request.POST, request.FILES), request.user, request=request
                )
                if op == "publish":
                    cms.publish(section, request.user, request=request)
                    messages.success(request, f"Published (version {section.version}).")
                else:
                    messages.success(request, "Draft saved.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("superadmin:cms_section", pk=pk)
    working = section.draft_content if section.draft_content is not None else section.content
    return render(
        request,
        "panel/admin/cms/section.html",
        {
            "section": section,
            "fields": cms_form.editor_fields(schema, working or {}),
            "versions": section.versions.select_related("published_by")[:20],
            "can_manage": has_perm(request.user, "cms.manage"),
        },
    )


# ------------------------------------------------------------------ email templates (NOTI-01)
@staff_perm("email_templates.manage")
def email_template_list(request):
    return render(request, "panel/admin/email_templates/list.html", {"templates": EmailTemplate.objects.all()})


@staff_perm("email_templates.manage")
def email_template_form(request, pk):
    tpl = get_object_or_404(EmailTemplate, pk=pk)
    form = EmailTemplateForm(request.POST or None, instance=tpl)
    if request.method == "POST" and form.is_valid():
        form.save()
        record(request, "email_template.update", "email_template", tpl.id)
        messages.success(request, "Template saved.")
        return redirect("superadmin:email_template_list")
    return render(request, "panel/admin/email_templates/form.html", {"form": form, "tpl": tpl})


# ------------------------------------------------------------------ logs (SA-17) & security (SA-18)
@staff_perm("logs.view")
def logs(request, kind="audit"):
    p = request.GET
    if kind == "api":
        qs = ApiRequestLog.objects.all()
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("q"):
            qs = qs.filter(Q(path__icontains=p["q"]) | Q(user_email__icontains=p["q"]))
    elif kind == "errors":
        qs = ErrorLog.objects.all()
        if p.get("q"):
            qs = qs.filter(Q(message__icontains=p["q"]) | Q(path__icontains=p["q"]))
    else:
        qs = AuditLog.objects.all()
        if kind == "security":
            qs = qs.filter(category="security")
        if p.get("q"):
            qs = qs.filter(
                Q(action__icontains=p["q"]) | Q(actor_email__icontains=p["q"]) | Q(entity_id__icontains=p["q"])
            )
        if p.get("from"):
            qs = qs.filter(created_at__date__gte=p["from"])
        if p.get("to"):
            qs = qs.filter(created_at__date__lte=p["to"])
    return render(request, "panel/admin/logs.html", {"page": page_of(request, qs), "kind": kind, "params": p})


@staff_perm("security.manage")
def sessions(request):
    if request.method == "POST":
        session = get_object_or_404(UserSession, pk=request.POST.get("session"))
        session.end()
        record(request, "session.end", "user", session.user_id, category="security")
        messages.success(request, "Session ended.")
        return redirect("superadmin:sessions")
    qs = UserSession.objects.select_related("user").order_by("-last_seen_at")
    return render(request, "panel/admin/sessions.html", {"page": page_of(request, qs)})


# ------------------------------------------------------------------ company approval (AUTH-12)
@require_POST
@staff_perm("companies.approve")
def company_approve(request, pk):
    company = get_object_or_404(Company, pk=pk)
    try:
        if request.POST.get("decision") == "reject":
            tenancy.reject_company(company, request.POST.get("reason", ""), request=request)
            messages.success(request, "Registration rejected; the owner was emailed.")
        else:
            tenancy.approve_company(company, request=request)
            messages.success(request, "Company approved; the owner was emailed.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("superadmin:company_detail", pk=pk)


# ------------------------------------------------------------------ industries (Phase 2 list; templates in Phase 3)
@staff_perm("industries.manage")
def industry_list(request):
    return render(
        request,
        "panel/admin/industries/list.html",
        {"industries": Industry.objects.annotate(company_count=Count("companies")).order_by(*Industry._meta.ordering)},
    )


@staff_perm("industries.manage")
def industry_form(request, pk=None):
    item = get_object_or_404(Industry, pk=pk) if pk else None
    form = IndustryForm(request.POST or None, request.FILES or None, instance=item)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        record(request, "industry.save", "industry", item.id, changes=form.changed_data)
        messages.success(request, "Industry saved.")
        return redirect("superadmin:industry_list")
    return render(
        request,
        "panel/admin/form.html",
        {"form": form, "title": f"Industry: {item}" if item else "New industry", "back": "superadmin:industry_list"},
    )


# ------------------------------------------------------------------ website enquiries (WEB-06)
@staff_perm("enquiries.view")
def enquiry_list(request):
    qs = Enquiry.objects.select_related("industry")
    q, status = request.GET.get("q", ""), request.GET.get("status", "")
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(business_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "panel/admin/enquiries/list.html",
        {"page": page_of(request, qs), "q": q, "status": status, "statuses": Enquiry.STATUSES},
    )


@staff_perm("enquiries.view")
def enquiry_detail(request, pk):
    enquiry = get_object_or_404(Enquiry.objects.select_related("industry", "handled_by"), pk=pk)
    form = EnquiryForm(request.POST or None, instance=enquiry)
    if request.method == "POST":
        if not has_perm(request.user, "enquiries.manage"):
            raise PermissionDenied
        if form.is_valid():
            website.update_enquiry(
                enquiry, form.cleaned_data["status"], form.cleaned_data["notes"], request.user, request
            )
            messages.success(request, "Enquiry updated.")
            return redirect("superadmin:enquiry_detail", pk=pk)
    return render(request, "panel/admin/enquiries/detail.html", {"enquiry": enquiry, "form": form})


# ------------------------------------------------------------------ AI settings (SA-09)
def _provider_page(request, page):
    """Vendor cards, key popup, on/off toggles (and model per task for AI). Talks to /api/v1/admin/* (no reloads)."""
    from apps.api.views_ai import ProviderSerializer
    from apps.providers.models import LLM_CAPABILITIES, TASKS, VOICE_CAPABILITIES, Provider
    from apps.providers.services import production, routes
    from apps.providers.vendors import VENDORS

    caps = dict(LLM_CAPABILITIES if page == "ai" else VOICE_CAPABILITIES)
    rows = [p for p in Provider.objects.prefetch_related("routes", "speech_routes") if set(p.capabilities) & set(caps)]
    chains = routes() if page == "ai" else {}
    data = {
        "page": page,
        "providers": ProviderSerializer(rows, many=True).data,
        "tasks": (
            [
                {
                    "task": key,
                    "label": label,
                    "capability": cap,
                    "routes": [
                        {"provider": str(r.provider_id), "model": r.model, "params": r.params} for r in chains[key]
                    ],
                }
                for key, label, cap in TASKS
            ]
            if page == "ai"
            else []
        ),
        "capabilities": caps,
        "adapters": dict(Provider.ADAPTERS),
        "vendors": {
            k: {
                **v,
                "config": [
                    {"name": n, "label": lb, "placeholder": ph, "required": rq} for n, lb, ph, rq in v["config"]
                ],
            }
            for k, v in VENDORS.items()
        },
        "currency": config.get("locale.currency"),
        "production": production(),
    }
    return render(request, "panel/admin/ai/settings.html", {"data": data})


@staff_perm("ai_providers.manage")
def ai_settings(request):
    return _provider_page(request, "ai")


@staff_perm("voice_settings.manage")
def voice_settings(request):
    """SA-10: speech-to-text, text-to-speech and telephony vendors."""
    return _provider_page(request, "voice")


@staff_perm("calls_oversight.view")
def calls(request):
    """SA-15: global call log across companies with filters and quality metrics (VOICE-22, ENGR-05 alerts)."""
    import statistics
    from datetime import timedelta

    from django.utils import timezone

    from apps.voice.models import Call

    with platform_context():
        qs = Call.all_companies.select_related("company", "employee", "lead")
        p = request.GET
        for key, field in (
            ("company", "company_id"),
            ("status", "status"),
            ("direction", "direction"),
            ("reason", "reason"),
        ):
            if p.get(key):
                qs = qs.filter(**{field: p[key]})
        if p.get("slow"):
            qs = qs.filter(metrics__p95_ms__gt=config.get("voice.latency_alert_p95_ms"))
        page = Paginator(qs, 30).get_page(p.get("page"))
        page.object_list = list(page.object_list)  # loaded inside the platform context (row-level security)
        day = list(
            Call.all_companies.filter(queued_at__gte=timezone.now() - timedelta(hours=24)).values_list(
                "status", "metrics", "duration_sec"
            )
        )
        companies = Company.objects.filter(deleted_at__isnull=True).order_by("name")
    p50s = [m.get("p50_ms") for _, m, _ in day if (m or {}).get("p50_ms")]
    p95s = [m.get("p95_ms") for _, m, _ in day if (m or {}).get("p95_ms")]
    limit50, limit95 = config.get("voice.latency_alert_p50_ms"), config.get("voice.latency_alert_p95_ms")
    summary = {
        "calls": len(day),
        "answered": sum(1 for s, _, d in day if d),
        "minutes": round(sum(d or 0 for _, _, d in day) / 60),
        "p50": round(statistics.median(p50s)) if p50s else None,
        "p95": round(statistics.median(p95s)) if p95s else None,
        "slow": sum(1 for v in p95s if v > limit95),
        "errors": sum(len((m or {}).get("errors") or []) for _, m, _ in day),
        "limit50": limit50,
        "limit95": limit95,
    }
    return render(
        request,
        "panel/admin/voice/calls.html",
        {"page": page, "summary": summary, "companies": companies, "statuses": Call.STATUSES, "p": p},
    )


@staff_perm("calls_oversight.view")
def call_detail(request, pk):
    from apps.voice.models import Call, Handoff

    with platform_context():
        call = get_object_or_404(
            Call.all_companies.select_related("company", "employee", "lead", "conversation"), pk=pk
        )
        conv = call.conversation
        msgs = list(conv.messages.all()) if conv else []
        tools = list(conv.tool_invocations.all()) if conv else []
        handoffs = list(Handoff.all_companies.filter(call=call).select_related("assigned_user"))
    return render(
        request,
        "panel/admin/voice/call.html",
        {
            "call": call,
            "conv": conv,
            "msgs": msgs,
            "tools": tools,
            "handoffs": handoffs,
            "turns": (call.metrics or {}).get("turns", [])[:50],
            "can_listen": has_perm(request.user, "recordings_oversight.listen"),
            "thresholds": {
                "p50": config.get("voice.latency_alert_p50_ms"),
                "p95": config.get("voice.latency_alert_p95_ms"),
            },
        },
    )


@staff_perm("recordings_oversight.listen")
def call_recording(request, pk):
    """Platform staff listening to a company's recording — audited (REC-03)."""
    from apps.voice import services as voice
    from apps.voice.models import Call

    with platform_context():
        call = get_object_or_404(Call.all_companies.select_related("company"), pk=pk)
    try:
        return redirect(voice.recording_link(call, request.user, False, request, platform=True))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("superadmin:call_detail", pk=pk)


@staff_perm("number_pool.manage")
def phone_numbers(request):
    """VOICE-16: the number pool — add numbers of a telephony provider and give them to companies (no reloads)."""
    from apps.api.views_voice import AdminPhoneNumberSerializer
    from apps.providers.models import Provider
    from apps.voice.models import PhoneNumber

    data = {
        "numbers": AdminPhoneNumberSerializer(
            PhoneNumber.objects.select_related("provider", "company", "employee"), many=True
        ).data,
        "providers": [
            {"key": p.key, "name": p.name, "is_active": p.is_active}
            for p in Provider.objects.filter(capabilities__contains=["telephony"])
        ],
        "companies": [
            {"id": str(c.pk), "name": c.name}
            for c in Company.objects.filter(status__in=[Company.ACTIVE, Company.TRIAL]).order_by("name")
        ],
        "capabilities": [{"key": k, "label": label} for k, label in PhoneNumber.CAPABILITIES],
        "webhooks": _webhook_help(),
    }
    return render(request, "panel/admin/voice/numbers.html", {"data": data})


def _webhook_help():
    """The callback addresses to paste into each telephony provider's console."""
    from apps.providers.models import Provider
    from apps.voice.services import webhook_url

    return [
        {"name": p.name, "answer": webhook_url(p, "answer"), "status": webhook_url(p, "status")}
        for p in Provider.objects.filter(capabilities__contains=["telephony"])
    ]


@staff_perm("voice_settings.manage")
def languages(request):
    """SA-11: languages (texts, speech routes with failover) and the voice catalogue. Talks to the REST API."""
    from apps.api.views_ai import LanguageSerializer, ProviderSerializer, VoiceSerializer, language_page_data
    from apps.providers.models import Language, Provider, Voice

    speech = [
        p for p in Provider.objects.prefetch_related("routes", "speech_routes") if {"stt", "tts"} & set(p.capabilities)
    ]
    data = {
        **language_page_data(),
        "languages": LanguageSerializer(
            Language.objects.prefetch_related("routes__provider", "routes__voice", "voices"), many=True
        ).data,
        "voices": VoiceSerializer(Voice.objects.select_related("language", "provider"), many=True).data,
        "providers": ProviderSerializer(speech, many=True).data,
    }
    return render(request, "panel/admin/voice/languages.html", {"data": data})


# ------------------------------------------------------------------ AI Employees of all companies (SA-08, EMP-14)
@staff_perm("ai_oversight.view")
def ai_employees(request):
    from apps.agents import services as agents
    from apps.agents.models import AIEmployee

    if request.method == "POST":
        if not has_perm(request.user, "ai_oversight.manage"):
            raise PermissionDenied
        company = get_object_or_404(Company, pk=request.POST.get("company"))
        try:
            employee = agents.create_from_template(company, request.user, request, force=True)
            if not employee:
                raise ValidationError("The company needs an industry with a published template.")
            messages.success(request, f"{employee.name} created for {company.name} (draft).")
            return redirect("superadmin:ai_employee", pk=employee.pk)
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("superadmin:company_detail", pk=company.pk)
    with platform_context():
        qs = AIEmployee.all_companies.select_related("company", "industry", "role")
        if request.GET.get("status"):
            qs = qs.filter(status=request.GET["status"])
        if request.GET.get("q"):
            qs = qs.filter(Q(name__icontains=request.GET["q"]) | Q(company__name__icontains=request.GET["q"]))
        page = page_of(request, qs.order_by("company__name", "name"))
        stats = agents.stats(list(page))
    return render(
        request,
        "panel/admin/ai/employees.html",
        {"page": page, "stats": stats, "statuses": AIEmployee.STATUSES, "p": request.GET},
    )


@staff_perm("ai_oversight.view")
def ai_employee(request, pk):
    from apps.agents import services as agents
    from apps.agents.models import AIEmployee, Conversation
    from apps.tenancy.context import company_context

    with platform_context():
        employee = get_object_or_404(AIEmployee.all_companies.select_related("company", "industry", "role"), pk=pk)
    if request.method == "POST":
        if not has_perm(request.user, "ai_oversight.manage"):
            raise PermissionDenied
        op = request.POST.get("op")
        with company_context(employee.company_id):
            try:
                if op == "pause":
                    agents.pause(
                        employee, request.POST.get("reason") or "Paused by the platform", True, request.user, request
                    )
                    messages.success(request, "Paused. The company cannot switch it on until you release it.")
                elif op == "release":
                    agents.release_platform_pause(employee, request)
                    messages.success(request, "Released: the company can activate it again.")
                elif op == "role":
                    agents.change_role(employee, request.POST.get("role"), request.user, request)
                    messages.success(request, "Role changed.")
            except ValidationError as exc:
                _errors(request, exc)
        return redirect("superadmin:ai_employee", pk=pk)
    with company_context(employee.company_id):
        context = {
            "employee": employee,
            "stats": agents.stats([employee])[employee.pk],
            "versions": list(employee.versions.all()[:30]),
            "conversations": list(Conversation.objects.filter(employee=employee).select_related("lead")[:20]),
            "roles": agents.roles_for(employee.company, employee.industry),
            "can_manage": has_perm(request.user, "ai_oversight.manage"),
        }
    return render(request, "panel/admin/ai/employee.html", context)


@staff_perm("ai_oversight.view")
def conversation(request, pk):
    """TOOL-14: transcript and tool log of any conversation."""
    from apps.agents.models import Conversation
    from apps.tenancy.context import company_context

    with platform_context():
        conv = get_object_or_404(Conversation.all_companies.select_related("employee", "lead", "company"), pk=pk)
    with company_context(conv.company_id):
        conv.message_list = list(conv.messages.all())
        conv.tool_list = list(conv.tool_invocations.all())
        return render(request, "panel/admin/ai/conversation.html", {"conv": conv})
