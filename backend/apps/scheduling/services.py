"""Calendar logic (CAL-02 … CAL-05, CAL-08, CAL-09). Panel, API and (Phase 4) the AI booking tools call these.

Double booking is prevented in the database: every booking or reschedule locks the resource row
(SELECT … FOR UPDATE) inside a transaction, then re-checks capacity, so concurrent requests are serialised.
"""

import datetime
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.industries import services as templates
from apps.industries.models import Holiday
from apps.platform_config import services as config

from .models import Appointment, AppointmentCounter, AvailabilityException, Resource

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ------------------------------------------------------------------ time helpers
def tz_for(resource):
    company = resource.company
    return ZoneInfo(resource.timezone or company.timezone or config.get("locale.timezone"))


def _parse_hm(value):
    hours, minutes = str(value).split(":")
    return datetime.time(int(hours), int(minutes))


def clean_working_hours(raw):
    """{"mon": [["09:00", "13:00"], ["14:00", "18:00"]], …} — gaps are breaks. Accepts "09:00-13:00, 14:00-18:00"."""
    out = {}
    for day in WEEKDAYS:
        value = (raw or {}).get(day) or []
        if isinstance(value, str):
            value = [part.split("-") for part in value.replace(" ", "").split(",") if part]
        intervals = []
        for pair in value:
            try:
                start, end = _parse_hm(pair[0]), _parse_hm(pair[1])
            except (ValueError, IndexError, TypeError):
                raise ValidationError(f"{day.title()}: use HH:MM-HH:MM, e.g. 09:00-13:00, 14:00-18:00.") from None
            if start >= end:
                raise ValidationError(f"{day.title()}: each period must end after it starts.")
            intervals.append([start.strftime("%H:%M"), end.strftime("%H:%M")])
        intervals.sort()
        for a, b in zip(intervals, intervals[1:], strict=False):
            if b[0] < a[1]:
                raise ValidationError(f"{day.title()}: periods overlap.")
        out[day] = intervals
    return out


def holidays_on(company, date):
    """CAL-09: platform holidays (Super Admin) and company holidays (company settings)."""
    names = list(Holiday.objects.filter(date=date).values_list("name", flat=True))
    names += [h.get("name") or "Holiday" for h in company.holidays or [] if h.get("date") == date.isoformat()]
    return names


def _day_intervals(resource, date):
    """Working periods for a date in the resource's timezone (without exceptions)."""
    tz = tz_for(resource)
    day = WEEKDAYS[date.weekday()]
    periods = (resource.working_hours or {}).get(day)
    if not resource.working_hours:  # fall back to company business hours
        hours = (resource.company.business_hours or {}).get(day) or {}
        periods = [] if hours.get("closed") or not hours.get("open") else [[hours["open"], hours["close"]]]
    return [
        (datetime.datetime.combine(date, _parse_hm(a), tz), datetime.datetime.combine(date, _parse_hm(b), tz))
        for a, b in periods or []
    ]


def _subtract(intervals, start, end):
    out = []
    for a, b in intervals:
        if end <= a or start >= b:
            out.append((a, b))
            continue
        if a < start:
            out.append((a, start))
        if end < b:
            out.append((end, b))
    return out


def working_intervals(resource, date):
    if holidays_on(resource.company, date):
        return []
    intervals = _day_intervals(resource, date)
    tz = tz_for(resource)
    day_start = datetime.datetime.combine(date, datetime.time.min, tz)
    day_end = day_start + datetime.timedelta(days=1)
    for exc in AvailabilityException.all_companies.filter(
        resource=resource, starts_at__lt=day_end, ends_at__gt=day_start
    ):
        if exc.kind == "extra":
            intervals.append((max(exc.starts_at, day_start), min(exc.ends_at, day_end)))
        else:
            intervals = _subtract(intervals, exc.starts_at, exc.ends_at)
    return sorted(intervals)


# ------------------------------------------------------------------ availability (CAL-03)
def _buffer(resource, appt_type):
    return datetime.timedelta(minutes=max(resource.buffer_minutes, appt_type.buffer_min))


def _overlapping(resource, start, end, buffer, exclude=None):
    qs = Appointment.all_companies.filter(
        resource=resource, status__in=Appointment.ACTIVE, starts_at__lt=end + buffer, ends_at__gt=start - buffer
    )
    if exclude:
        qs = qs.exclude(pk=exclude.pk)
    return qs.count()


def check_slot(resource, appt_type, start, exclude=None, now=None):
    """Raises ValidationError when `start` cannot be booked (rules + capacity)."""
    now = now or timezone.now()
    if not resource.is_active:
        raise ValidationError("This calendar is not active.")
    if resource.appointment_types and appt_type.key not in resource.appointment_types:
        raise ValidationError(f"{resource.name} does not take {appt_type.name} bookings.")
    end = start + datetime.timedelta(minutes=appt_type.duration_min)
    if start < now + datetime.timedelta(minutes=resource.min_notice_minutes):
        raise ValidationError(f"Bookings need at least {resource.min_notice_minutes} minutes' notice.")
    if start > now + datetime.timedelta(days=resource.booking_window_days):
        raise ValidationError(f"Bookings can be made up to {resource.booking_window_days} days ahead.")
    local_date = start.astimezone(tz_for(resource)).date()
    if holidays_on(resource.company, local_date):
        raise ValidationError(f"{local_date:%d %b %Y} is a holiday.")
    if not any(a <= start and end <= b for a, b in working_intervals(resource, local_date)):
        raise ValidationError("That time is outside working hours.")
    if _overlapping(resource, start, end, _buffer(resource, appt_type), exclude) >= resource.max_per_slot:
        raise ValidationError("That slot is already booked.")
    return end


def available_slots(resource, appt_type, date, now=None):
    """CAL-03: bookable start times for one day (aware datetimes)."""
    if resource.appointment_types and appt_type.key not in resource.appointment_types:
        return []
    now = now or timezone.now()
    step = datetime.timedelta(minutes=resource.slot_minutes or 30)
    duration = datetime.timedelta(minutes=appt_type.duration_min)
    earliest = now + datetime.timedelta(minutes=resource.min_notice_minutes)
    latest = now + datetime.timedelta(days=resource.booking_window_days)
    buffer = _buffer(resource, appt_type)
    tz = tz_for(resource)
    day_start = datetime.datetime.combine(date, datetime.time.min, tz)
    booked = list(
        Appointment.all_companies.filter(
            resource=resource,
            status__in=Appointment.ACTIVE,
            starts_at__lt=day_start + datetime.timedelta(days=1, hours=2),
            ends_at__gt=day_start - datetime.timedelta(hours=2),
        ).values_list("starts_at", "ends_at")
    )
    slots = []
    for a, b in working_intervals(resource, date):
        start = a
        while start + duration <= b:
            end = start + duration
            taken = sum(1 for s, e in booked if s < end + buffer and e > start - buffer)
            if earliest <= start <= latest and taken < resource.max_per_slot:
                slots.append(start)
            start += step
    return slots


# ------------------------------------------------------------------ booking (CAL-05, CAL-08)
def _next_number(company):
    counter, _ = AppointmentCounter.all_companies.get_or_create(company=company)
    counter = AppointmentCounter.all_companies.select_for_update().get(pk=counter.pk)
    counter.value += 1
    counter.save(update_fields=["value", "updated_at"])
    return counter.value


def _type(company, appt_type):
    if hasattr(appt_type, "duration_min"):
        return appt_type
    for t in templates.appointment_types(company):
        if t.key == appt_type or str(t.pk) == str(appt_type):
            return t
    raise ValidationError("Unknown appointment type.")


@transaction.atomic
def book(
    company,
    resource,
    appt_type,
    start,
    lead=None,
    user=None,
    created_by_type="user",
    channel="manual",
    location="",
    meeting_link="",
    notes="",
    assigned_user=None,
    request=None,
):
    appt_type = _type(company, appt_type)
    if resource.company_id != company.id or (lead and lead.company_id != company.id):
        raise ValidationError("Not found.")
    resource = Resource.all_companies.select_for_update().get(pk=resource.pk)  # serialises bookings
    if timezone.is_naive(start):
        start = start.replace(tzinfo=tz_for(resource))
    end = check_slot(resource, appt_type, start)
    appt = Appointment.objects.create(
        company=company,
        number=_next_number(company),
        lead=lead,
        appointment_type=appt_type,
        resource=resource,
        assigned_user=assigned_user or resource.user,
        starts_at=start,
        ends_at=end,
        location=location,
        meeting_link=meeting_link,
        notes=notes,
        created_by_type=created_by_type,
        created_by=user if user and user.is_authenticated else None,
        channel=channel,
    )
    if lead:
        from apps.crm import services as crm

        crm.log(
            lead,
            "appointment",
            f"{appt_type.name} booked for {timezone.localtime(start):%d %b %Y %H:%M} with {resource.name}",
            user,
            actor_type=created_by_type,
            appointment=str(appt.pk),
        )
        crm.apply_event(lead, "appointment_booked", user, actor_type=created_by_type)
    record(request, "appointment.book", "appointment", appt.id, company=company)
    return appt


@transaction.atomic
def reschedule(appt, start, user=None, request=None):
    if appt.status not in Appointment.ACTIVE:
        raise ValidationError("Only upcoming appointments can be rescheduled.")
    resource = Resource.all_companies.select_for_update().get(pk=appt.resource_id)
    if timezone.is_naive(start):
        start = start.replace(tzinfo=tz_for(resource))
    old = appt.starts_at
    appt.ends_at = check_slot(resource, appt.appointment_type, start, exclude=appt)
    appt.starts_at, appt.status = start, Appointment.RESCHEDULED
    appt.save(update_fields=["starts_at", "ends_at", "status", "updated_at"])
    if appt.lead_id:
        from apps.crm import services as crm

        crm.log(
            appt.lead,
            "appointment",
            f"{appt.reference} moved from {timezone.localtime(old):%d %b %H:%M} to "
            f"{timezone.localtime(start):%d %b %Y %H:%M}",
            user,
        )
    record(request, "appointment.reschedule", "appointment", appt.id, company=appt.company)
    return appt


def set_status(appt, status, reason="", user=None, request=None):
    if status not in dict(Appointment.STATUSES) or status == Appointment.RESCHEDULED:
        raise ValidationError("Unknown status.")
    if status == Appointment.CANCELLED and not (reason or "").strip():
        raise ValidationError("Give a reason for cancelling.")
    appt.status = status
    appt.cancel_reason = (reason or "")[:255] if status == Appointment.CANCELLED else appt.cancel_reason
    appt.save(update_fields=["status", "cancel_reason", "updated_at"])
    if appt.lead_id:
        from apps.crm import services as crm

        crm.log(
            appt.lead,
            "appointment",
            f"{appt.reference} {appt.get_status_display().lower()}" + (f": {reason}" if reason else ""),
            user,
        )
    record(request, f"appointment.{status}", "appointment", appt.id, company=appt.company)
    return appt


# ------------------------------------------------------------------ resources
def save_resource(company, data, resource=None, request=None):
    resource = resource or Resource(company=company)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Give the calendar a name.")
    resource.name = name[:120]
    resource.kind = data.get("kind") if data.get("kind") in dict(Resource.KINDS) else "other"
    resource.timezone = str(data.get("timezone") or "")
    resource.working_hours = clean_working_hours(data.get("working_hours")) if data.get("working_hours") else {}
    for field in ("slot_minutes", "buffer_minutes", "max_per_slot", "min_notice_minutes", "booking_window_days"):
        if data.get(field) not in (None, ""):
            try:
                value = int(data[field])
            except (TypeError, ValueError):
                raise ValidationError(f"{field.replace('_', ' ').title()}: enter a whole number.") from None
            if value < (1 if field in ("slot_minutes", "max_per_slot", "booking_window_days") else 0):
                raise ValidationError(f"{field.replace('_', ' ').title()}: too small.")
            setattr(resource, field, value)
    resource.appointment_types = [k for k in data.get("appointment_types") or [] if k]
    resource.is_active = bool(data.get("is_active", True))
    if data.get("user"):
        from apps.crm.services import _member

        resource.user = _member(company, data["user"])
    else:
        resource.user = None
    resource.save()
    record(request, "calendar.resource_save", "calendar_resource", resource.id, company=company)
    return resource


def add_exception(resource, kind, starts_at, ends_at, note="", request=None):
    if kind not in dict(AvailabilityException.KINDS):
        raise ValidationError("Unknown kind.")
    if not starts_at or not ends_at or starts_at >= ends_at:
        raise ValidationError("The end must be after the start.")
    tz = tz_for(resource)
    starts_at = starts_at if timezone.is_aware(starts_at) else starts_at.replace(tzinfo=tz)
    ends_at = ends_at if timezone.is_aware(ends_at) else ends_at.replace(tzinfo=tz)
    exc = AvailabilityException.objects.create(
        company_id=resource.company_id,
        resource=resource,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        note=note[:200],
    )
    record(request, "calendar.exception_add", "calendar_resource", resource.id, company=resource.company)
    return exc
