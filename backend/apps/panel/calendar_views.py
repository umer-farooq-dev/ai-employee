"""Company panel: built-in calendar (CAL-01 … CAL-05, CAL-08, CAL-09). Logic lives in apps.scheduling.services."""

import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.crm import services as crm
from apps.industries import services as templates
from apps.industries.models import Holiday
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm
from apps.scheduling import notices
from apps.scheduling import services as calendar
from apps.scheduling.models import Appointment, AvailabilityException, Resource

from .company_views import _errors, company_perm


def _can(request, key):
    return has_perm(request.user, key, request.company)


@company_perm("calendar.view")
def index(request):
    return render(
        request,
        "panel/company/calendar/index.html",
        {
            "resources": Resource.objects.filter(is_active=True),
            "resource_id": request.GET.get("resource", ""),
            "can_book": _can(request, "calendar.manage"),
            "can_configure": _can(request, "calendar.configure"),
        },
    )


@company_perm("calendar.view")
def events(request):
    """FullCalendar feed: appointments + platform / company holidays (background)."""
    start = parse_datetime(request.GET.get("start", "")) or timezone.now() - datetime.timedelta(days=31)
    end = parse_datetime(request.GET.get("end", "")) or timezone.now() + datetime.timedelta(days=31)
    qs = (
        Appointment.objects.filter(starts_at__lt=end, ends_at__gt=start)
        .exclude(status=Appointment.CANCELLED)
        .select_related("appointment_type", "resource", "lead")
    )
    if request.GET.get("resource"):
        qs = qs.filter(resource_id=request.GET["resource"])
    colors = {"completed": "#198754", "no_show": "#6c757d", "confirmed": "#0d6efd"}
    data = [
        {
            "id": str(a.pk),
            "title": f"{a.appointment_type.name} · {a.lead.name if a.lead_id else a.resource.name}",
            "start": a.starts_at.isoformat(),
            "end": a.ends_at.isoformat(),
            "url": reverse("panel:appointment", args=[a.pk]),
            "color": colors.get(a.status, "#20c997"),
        }
        for a in qs
    ]
    first, last = start.date(), end.date()
    for h in Holiday.objects.filter(date__gte=first, date__lte=last):
        data.append(
            {"title": h.name, "start": h.date.isoformat(), "allDay": True, "display": "background", "color": "#ffc107"}
        )
    for h in request.company.holidays or []:
        d = parse_date(h.get("date", ""))
        if d and first <= d <= last:
            data.append(
                {
                    "title": h.get("name", "Holiday"),
                    "start": d.isoformat(),
                    "allDay": True,
                    "display": "background",
                    "color": "#ffc107",
                }
            )
    return JsonResponse(data, safe=False)


@company_perm("calendar.manage")
def book(request):
    """CAL-08 manual booking: choose calendar, type and date → pick a free slot."""
    company = request.company
    p = request.POST if request.method == "POST" else request.GET
    resources = list(Resource.objects.filter(is_active=True))
    types = templates.appointment_types(company)
    resource = next((r for r in resources if str(r.pk) == p.get("resource")), resources[0] if resources else None)
    appt_type = next((t for t in types if t.key == p.get("type")), types[0] if types else None)
    date = parse_date(p.get("date") or "") or timezone.localdate()
    lead = crm.visible(request).filter(pk=p.get("lead")).first() if p.get("lead") else None
    if request.method == "POST":
        try:
            start = parse_datetime(request.POST.get("start", ""))
            if not (resource and appt_type and start):
                raise ValidationError("Choose a calendar, an appointment type and a time.")
            appt = calendar.book(
                company,
                resource,
                appt_type,
                start,
                lead=lead,
                user=request.user,
                location=request.POST.get("location", ""),
                meeting_link=request.POST.get("meeting_link", ""),
                notes=request.POST.get("notes", ""),
                request=request,
            )
            messages.success(request, f"{appt.reference} booked.")
            return redirect("panel:appointment", pk=appt.pk)
        except ValidationError as exc:
            _errors(request, exc)
    slots = calendar.available_slots(resource, appt_type, date) if resource and appt_type else []
    return render(
        request,
        "panel/company/calendar/book.html",
        {
            "resources": resources,
            "types": types,
            "resource": resource,
            "appt_type": appt_type,
            "date": date,
            "slots": slots,
            "lead": lead,
            "holidays": calendar.holidays_on(company, date),
            "leads": crm.visible(request).order_by("-updated_at")[:200],
        },
    )


@company_perm("calendar.view")
def appointment(request, pk):
    appt = get_object_or_404(Appointment.objects.select_related("appointment_type", "resource", "lead"), pk=pk)
    date = parse_date(request.GET.get("date") or "") or timezone.localdate(appt.starts_at)
    if request.method == "POST":
        if not _can(request, "calendar.manage"):
            raise PermissionDenied
        try:
            if request.POST.get("op") == "resend":
                sent = [n for n in notices.resend(appt, request.user, request) if n.status == "sent"]
                messages.success(request, f"Confirmation sent on {len(sent)} channel(s); see Messages below.")
                return redirect("panel:appointment", pk=pk)
            if request.POST.get("op") == "reschedule":
                start = parse_datetime(request.POST.get("start", ""))
                if not start:
                    raise ValidationError("Pick a new time.")
                calendar.reschedule(appt, start, request.user, request=request)
            else:
                calendar.set_status(
                    appt, request.POST.get("status"), request.POST.get("reason", ""), request.user, request=request
                )
            messages.success(request, "Appointment updated.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:appointment", pk=pk)
    reschedule_slots = (
        calendar.available_slots(appt.resource, appt.appointment_type, date)
        if appt.status in Appointment.ACTIVE
        else []
    )
    return render(
        request,
        "panel/company/calendar/appointment.html",
        {
            "appt": appt,
            "date": date,
            "slots": reschedule_slots,
            "can_manage": _can(request, "calendar.manage"),
            "upcoming": appt.status in Appointment.ACTIVE,
            "notices": appt.notices.select_related("wa_message"),
            "can_configure": _can(request, "calendar.configure"),
        },
    )


@company_perm("calendar.configure")
def messages_settings(request):
    """CAL-07 / CAL-10: confirmations, reminders and team alerts — the company's choice or the platform default."""
    company = request.company
    if request.method == "POST":
        try:
            if request.POST.get("op") == "reset":
                notices.save_policy(company, {"use_platform": True}, request.user, request)
                messages.success(request, "Back to the platform defaults.")
            else:
                data = {k: request.POST.get(k) == "on" for k in notices.POLICY_KEYS if k != "reminder_hours"}
                data["reminder_hours"] = request.POST.get("reminder_hours", "")
                notices.save_policy(company, data, request.user, request)
                messages.success(request, "Appointment messages saved.")
            return redirect("panel:calendar_messages")
        except ValidationError as exc:
            _errors(request, exc)
    from apps.whatsapp.models import Template

    approved = set(
        Template.objects.filter(status=Template.APPROVED, purpose__in=set(notices.PURPOSES.values())).values_list(
            "purpose", flat=True
        )
    )
    return render(
        request,
        "panel/company/calendar/messages.html",
        {
            "rules": notices.policy(company),
            "own": bool((company.settings or {}).get("appointments")),
            "max_hours": setting("calendar.reminder_max_hours"),
            "wa_ready": {k: v in approved for k, v in notices.PURPOSES.items()},
            "can_whatsapp": _can(request, "whatsapp.manage"),
        },
    )


@company_perm("calendar.configure")
def resources(request):
    return render(request, "panel/company/calendar/resources.html", {"resources": Resource.objects.all()})


@company_perm("calendar.configure")
def resource_form(request, pk=None):
    company = request.company
    resource = get_object_or_404(Resource, pk=pk) if pk else None
    if request.method == "POST":
        try:
            op = request.POST.get("op", "save")
            if op == "exception" and resource:
                calendar.add_exception(
                    resource,
                    request.POST.get("kind"),
                    parse_datetime(request.POST.get("starts_at", "")),
                    parse_datetime(request.POST.get("ends_at", "")),
                    request.POST.get("note", ""),
                    request=request,
                )
                messages.success(request, "Added.")
            elif op == "remove_exception" and resource:
                AvailabilityException.objects.filter(resource=resource, pk=request.POST.get("exception")).delete()
            elif op == "delete" and resource:
                if resource.appointments.exists():
                    raise ValidationError("This calendar has appointments; switch it off instead.")
                resource.delete()
                messages.success(request, "Calendar deleted.")
                return redirect("panel:calendar_resources")
            else:
                data = {
                    **request.POST.dict(),
                    "appointment_types": request.POST.getlist("appointment_types"),
                    "is_active": bool(request.POST.get("is_active")),
                    "working_hours": {d: request.POST.get(f"wh_{d}", "") for d in calendar.WEEKDAYS},
                }
                if not any(data["working_hours"].values()):
                    data["working_hours"] = {}
                resource = calendar.save_resource(company, data, resource, request=request)
                messages.success(request, "Calendar saved.")
            return redirect("panel:calendar_resource_edit", pk=resource.pk)
        except ValidationError as exc:
            _errors(request, exc)
            if resource:
                return redirect("panel:calendar_resource_edit", pk=resource.pk)
    hours = {
        d: ", ".join(f"{a}-{b}" for a, b in ((resource.working_hours or {}).get(d) or [])) if resource else ""
        for d in calendar.WEEKDAYS
    }
    return render(
        request,
        "panel/company/calendar/resource_form.html",
        {
            "resource": resource,
            "hours": [(d, hours[d]) for d in calendar.WEEKDAYS],
            "types": templates.appointment_types(company),
            "members": crm.members(company),
            "kinds": Resource.KINDS,
            "exception_kinds": AvailabilityException.KINDS,
            "exceptions": resource.exceptions.filter(ends_at__gte=timezone.now()) if resource else [],
        },
    )
