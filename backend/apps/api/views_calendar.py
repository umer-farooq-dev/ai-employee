"""REST API for the calendar (CAL-01 … CAL-05, CAL-08, CAL-09): /api/v1/calendar/…"""

import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import services as crm
from apps.industries import services as templates
from apps.industries.models import Holiday
from apps.scheduling import notices
from apps.scheduling import services as calendar
from apps.scheduling.models import Appointment, AppointmentNotice, Resource

from .base import TenantContextMixin, perm
from .views_templates import AppointmentTypeSerializer


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class ResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resource
        fields = [
            "id",
            "kind",
            "name",
            "user",
            "timezone",
            "working_hours",
            "slot_minutes",
            "buffer_minutes",
            "max_per_slot",
            "min_notice_minutes",
            "booking_window_days",
            "appointment_types",
            "is_active",
        ]


class NoticeSerializer(serializers.ModelSerializer):
    delivery = serializers.CharField(source="wa_message.status", default="", read_only=True)

    class Meta:
        model = AppointmentNotice
        fields = ["kind", "channel", "recipient", "status", "detail", "offset_minutes", "for_start", "delivery"]
        read_only_fields = fields


class AppointmentSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    notices = NoticeSerializer(many=True, read_only=True)
    type = serializers.CharField(source="appointment_type.key", read_only=True)
    type_name = serializers.CharField(source="appointment_type.name", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "reference",
            "lead",
            "type",
            "type_name",
            "resource",
            "assigned_user",
            "starts_at",
            "ends_at",
            "status",
            "location",
            "meeting_link",
            "notes",
            "cancel_reason",
            "created_by_type",
            "channel",
            "created_at",
            "notices",
        ]
        read_only_fields = fields


class ResourceViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = ResourceSerializer
    pagination_class = None

    def get_permissions(self):
        key = "calendar.view" if self.request.method in permissions.SAFE_METHODS else "calendar.configure"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_queryset(self):
        return Resource.objects.all()

    def create(self, request):
        resource = _errors(calendar.save_resource, request.company, request.data, None, request._request)
        return Response(ResourceSerializer(resource).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        resource = self.get_object()
        data = {**ResourceSerializer(resource).data, **request.data}
        resource = _errors(calendar.save_resource, request.company, data, resource, request._request)
        return Response(ResourceSerializer(resource).data)

    update = partial_update

    def destroy(self, request, pk=None):
        resource = self.get_object()
        if resource.appointments.exists():
            raise ValidationError("This calendar has appointments; switch it off instead.")
        resource.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=dict, responses=dict)
    @action(detail=True, methods=["post"])
    def exceptions(self, request, pk=None):
        """Leave / blocked / extra time: {"kind", "starts_at", "ends_at", "note"}."""
        exc = _errors(
            calendar.add_exception,
            self.get_object(),
            request.data.get("kind"),
            parse_datetime(request.data.get("starts_at") or ""),
            parse_datetime(request.data.get("ends_at") or ""),
            request.data.get("note", ""),
            request._request,
        )
        return Response({"id": exc.id}, status=status.HTTP_201_CREATED)

    @extend_schema(responses=dict)
    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        """CAL-03: ?type=<key>&date=YYYY-MM-DD → free start times."""
        resource = self.get_object()
        appt_type = _errors(calendar._type, request.company, request.query_params.get("type", ""))
        date = parse_date(request.query_params.get("date") or "") or datetime.date.today()
        return Response(
            {
                "date": date,
                "holidays": calendar.holidays_on(request.company, date),
                "slots": [s.isoformat() for s in calendar.available_slots(resource, appt_type, date)],
            }
        )


class AppointmentViewSet(TenantContextMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """?from=&to= (ISO) &resource=&lead=&status= ; POST books, /reschedule/ and /status/ change it."""

    serializer_class = AppointmentSerializer

    def get_permissions(self):
        key = "calendar.view" if self.request.method in permissions.SAFE_METHODS else "calendar.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_queryset(self):
        qs = Appointment.objects.select_related("appointment_type").prefetch_related("notices__wa_message")
        p = self.request.query_params
        if parse_datetime(p.get("from") or ""):
            qs = qs.filter(ends_at__gt=parse_datetime(p["from"]))
        if parse_datetime(p.get("to") or ""):
            qs = qs.filter(starts_at__lt=parse_datetime(p["to"]))
        for key in ("resource", "lead", "status"):
            if p.get(key):
                qs = qs.filter(**{key if key == "status" else f"{key}_id": p[key]})
        return qs

    @extend_schema(request=dict, responses=AppointmentSerializer)
    def create(self, request):
        """{"resource", "type", "start" (ISO), "lead"?, "location"?, "meeting_link"?, "notes"?}"""
        resource = get_object_or_404(Resource, pk=request.data.get("resource"))
        lead = crm.visible(request).filter(pk=request.data.get("lead")).first() if request.data.get("lead") else None
        if request.data.get("lead") and not lead:
            raise ValidationError({"lead": "Not found."})
        start = parse_datetime(request.data.get("start") or "")
        if not start:
            raise ValidationError({"start": "Use ISO 8601, e.g. 2026-11-08T10:30:00+05:30."})
        appt = _errors(
            calendar.book,
            request.company,
            resource,
            request.data.get("type", ""),
            start,
            lead=lead,
            user=request.user,
            channel="api",
            location=request.data.get("location", ""),
            meeting_link=request.data.get("meeting_link", ""),
            notes=request.data.get("notes", ""),
            request=request._request,
        )
        return Response(AppointmentSerializer(appt).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=dict, responses=AppointmentSerializer)
    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        start = parse_datetime(request.data.get("start") or "")
        if not start:
            raise ValidationError({"start": "Required."})
        appt = _errors(calendar.reschedule, self.get_object(), start, request.user, request._request)
        return Response(AppointmentSerializer(appt).data)

    @extend_schema(request=dict, responses=AppointmentSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        appt = _errors(
            calendar.set_status,
            self.get_object(),
            request.data.get("status"),
            request.data.get("reason", ""),
            request.user,
            request._request,
        )
        return Response(AppointmentSerializer(appt).data)

    @extend_schema(request=None, responses=NoticeSerializer(many=True))
    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        """Send the customer confirmation again on the channels switched on (CAL-07)."""
        notes = _errors(notices.resend, self.get_object(), request.user, request._request)
        return Response(NoticeSerializer(notes, many=True).data)


class MessagesSettingsView(TenantContextMixin, APIView):
    """CAL-07 / CAL-10: GET the effective confirmations, reminders and team alerts; PATCH any of confirm_whatsapp,
    confirm_email, cancel_notice, reminder_hours (list of hours), reminder_whatsapp, reminder_email, notify_staff —
    or {"use_platform": true} for the platform defaults."""

    def get_permissions(self):
        key = "calendar.view" if self.request.method in permissions.SAFE_METHODS else "calendar.configure"
        return [permissions.IsAuthenticated(), perm(key)()]

    def _out(self, rules):
        own = bool((self.request.company.settings or {}).get("appointments"))
        return {**rules, "uses_platform_defaults": not own}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(self._out(notices.policy(request.company)))

    @extend_schema(request=dict, responses=dict)
    def patch(self, request):
        rules = _errors(notices.save_policy, request.company, request.data, request.user, request._request)
        return Response(self._out(rules))


class CalendarConfigView(TenantContextMixin, APIView):
    """Appointment types (from the template) and holidays in a date range (?from=&to= dates)."""

    permission_classes = [permissions.IsAuthenticated, perm("calendar.view")]

    @extend_schema(responses=dict)
    def get(self, request):
        first = parse_date(request.query_params.get("from") or "") or datetime.date.today()
        last = parse_date(request.query_params.get("to") or "") or first + datetime.timedelta(days=365)
        holidays = [
            {"date": h.date, "name": h.name, "scope": "platform"}
            for h in Holiday.objects.filter(date__gte=first, date__lte=last)
        ]
        holidays += [
            {"date": h["date"], "name": h.get("name", ""), "scope": "company"}
            for h in request.company.holidays or []
            if first.isoformat() <= h.get("date", "") <= last.isoformat()
        ]
        return Response(
            {
                "appointment_types": AppointmentTypeSerializer(
                    templates.appointment_types(request.company), many=True
                ).data,
                "holidays": sorted(holidays, key=lambda h: str(h["date"])),
            }
        )
