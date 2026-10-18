"""Company panel: call logs (VOICE-15, REC-01), Call now (VOICE-02), calling rules and numbers (CP-06, EMP-08)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.agents.models import AIEmployee
from apps.crm.models import Lead
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm
from apps.voice import services as voice
from apps.voice.models import Call, Handoff

from .company_views import _errors, company_perm


@company_perm("calls.view")
def call_list(request):
    qs = Call.objects.filter(company=request.company).select_related("employee", "lead", "conversation")
    p = request.GET
    for key, field in (
        ("employee", "employee_id"),
        ("direction", "direction"),
        ("status", "status"),
        ("reason", "reason"),
    ):
        if p.get(key):
            qs = qs.filter(**{field: p[key]})
    if p.get("q"):
        qs = (
            qs.filter(from_e164__icontains=p["q"])
            | qs.filter(to_e164__icontains=p["q"])
            | qs.filter(lead__name__icontains=p["q"])
        )
    page = Paginator(qs, 25).get_page(p.get("page"))
    return render(
        request,
        "panel/company/calls/list.html",
        {
            "page": page,
            "employees": AIEmployee.objects.filter(company=request.company),
            "statuses": Call.STATUSES,
            "reasons": Call.REASONS,
            "p": p,
        },
    )


@company_perm("calls.view")
def call_detail(request, pk):
    call = get_object_or_404(
        Call.objects.select_related("employee", "lead", "conversation", "phone_number", "requested_by"),
        pk=pk,
        company=request.company,
    )
    conv = call.conversation
    handoffs = Handoff.objects.filter(company=request.company, call=call).select_related("assigned_user")
    can = {
        "listen": has_perm(request.user, "recordings.listen", request.company),
        "download": has_perm(request.user, "recordings.download", request.company),
        "make": has_perm(request.user, "calls.make", request.company),
    }
    return render(
        request,
        "panel/company/calls/detail.html",
        {
            "call": call,
            "conv": conv,
            "msgs": conv.messages.all() if conv else [],
            "tools": conv.tool_invocations.all() if conv else [],
            "handoffs": handoffs,
            "can": can,
            "turns": (call.metrics or {}).get("turns", [])[:50],
            "thresholds": {"p50": setting("voice.latency_alert_p50_ms"), "p95": setting("voice.latency_alert_p95_ms")},
        },
    )


@company_perm("calls.make")
def call_now(request, lead_pk):
    """CRM-11 / VOICE-02: Call now from the lead page — compliance checks run first."""
    lead = get_object_or_404(Lead, pk=lead_pk, company=request.company, deleted_at__isnull=True)
    if request.method == "POST":
        employee = AIEmployee.objects.filter(company=request.company, pk=request.POST.get("employee")).first()
        try:
            if not employee:
                raise ValidationError("Choose the AI Employee who should call.")
            when = request.POST.get("when", "") if request.POST.get("schedule") else ""
            if request.POST.get("schedule") and not when:
                raise ValidationError("Choose a date and time for the follow-up call.")
            if when:
                from django.utils.dateparse import parse_datetime
                from django.utils.timezone import get_current_timezone, make_aware

                at = parse_datetime(when)
                if not at:
                    raise ValidationError("Choose a date and time for the follow-up call.")
                voice.schedule_follow_up(
                    employee, lead, make_aware(at, get_current_timezone()) if at.tzinfo is None else at, request.user
                )
                messages.success(
                    request, f"{employee.name} will call {lead.name or lead.reference} at {at:%d %b %Y %H:%M}."
                )
            else:
                call = voice.place_call(employee, lead, "call_now", request.user, request)
                if call.status == Call.FAILED:
                    messages.error(request, f"The call could not be placed: {call.error}")
                else:
                    messages.success(request, f"{employee.name} is calling {lead.name or lead.reference} now.")
        except ValidationError as exc:
            _errors(request, exc)
    return redirect("panel:lead_detail", pk=lead.pk)


@company_perm("company.view")
def calling_settings(request):
    """CP-06: the company's numbers (connected to AI Employees) and its calling rules within the platform limits."""
    company = request.company
    can_manage = has_perm(request.user, "phone_numbers.manage", company)
    if request.method == "POST":
        if not can_manage:
            messages.error(request, "You may not change calling settings.")
            return redirect("panel:calling_settings")
        try:
            if request.POST.get("op") == "number":
                number = get_object_or_404(voice.numbers_for(company), pk=request.POST.get("number"))
                ref = request.POST.get("employee")
                employee = AIEmployee.objects.filter(company=company, pk=ref).first() if ref else None
                voice.connect_number(company, number, employee, request.user, request)
                messages.success(
                    request, f"{number.e164} {'connected to ' + employee.name if employee else 'disconnected'}."
                )
            else:
                data = {k: request.POST.get(k, "") for k in voice.POLICY_KEYS}
                data["recording_enabled"] = request.POST.get("recording_enabled") == "on"
                voice.save_policy(company, data, request.user, request)
                messages.success(request, "Calling rules saved.")
            return redirect("panel:calling_settings")
        except ValidationError as exc:
            _errors(request, exc)
    own = (company.settings or {}).get("calling") or {}
    limits = {key: setting(skey) for key, (skey, _) in voice.POLICY_KEYS.items()}
    return render(
        request,
        "panel/company/calls/settings.html",
        {
            "numbers": voice.numbers_for(company),
            "employees": AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED),
            "own": own,
            "effective": voice.policy(company),
            "limits": limits,
            "can_manage": can_manage,
        },
    )
