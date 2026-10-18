"""REST API for voice calls (M14) — company panel, Super Admin and the future app.

Company:
/api/v1/phone-numbers/                 the company's numbers;  PATCH <id>/ {"employee": id | null}  (EMP-08)
/api/v1/calls/                         call log (?direction, status, employee, lead, reason);  POST {lead, employee}
                                       = Call now (VOICE-02; compliance checks first)
/api/v1/calls/<id>/                    call detail (REC-01);  POST <id>/cancel/
/api/v1/calls/schedule/                POST {lead, employee, at} — follow-up call at a time
/api/v1/calling-policy/                GET / PUT the company's calling rules (within platform limits, CP-06)
Super Admin:
/api/v1/admin/phone-numbers/           number pool CRUD (VOICE-16)
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AIEmployee
from apps.crm.models import Lead
from apps.voice import services
from apps.voice.models import Call, PhoneNumber

from .base import AdminViewSet, TenantContextMixin, any_perm, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class PhoneNumberSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    employee_name = serializers.CharField(source="employee.name", read_only=True, default="")

    class Meta:
        model = PhoneNumber
        fields = ["id", "e164", "label", "capabilities", "provider_name", "employee", "employee_name", "status"]
        read_only_fields = ["id", "e164", "label", "capabilities", "provider_name", "status"]


class PhoneNumberViewSet(TenantContextMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = PhoneNumberSerializer
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated(), any_perm("phone_numbers.manage", "ai_employees.view")()]
        return [permissions.IsAuthenticated(), perm("phone_numbers.manage")()]

    def get_queryset(self):
        return services.numbers_for(self.request.company)

    def partial_update(self, request, *args, **kwargs):
        number = self.get_object()
        ref = request.data.get("employee")
        employee = AIEmployee.objects.filter(company=request.company, pk=ref).first() if ref else None
        if ref and not employee:
            raise ValidationError({"employee": "Unknown AI Employee."})
        number = _errors(services.connect_number, request.company, number, employee, request.user, request._request)
        return Response(PhoneNumberSerializer(number).data)


class CallSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    lead_reference = serializers.CharField(source="lead.reference", read_only=True, default="")
    lead_name = serializers.CharField(source="lead.name", read_only=True, default="")

    class Meta:
        model = Call
        fields = [
            "id",
            "employee",
            "employee_name",
            "lead",
            "lead_reference",
            "lead_name",
            "conversation",
            "direction",
            "reason",
            "from_e164",
            "to_e164",
            "status",
            "attempt",
            "retry_of",
            "next_retry_at",
            "queued_at",
            "answered_at",
            "ended_at",
            "duration_sec",
            "hangup_by",
            "amd_result",
            "language",
            "transfer_status",
            "recording_status",
            "recording_seconds",
            "error",
        ]
        read_only_fields = fields


class CallDetailSerializer(CallSerializer):
    summary = serializers.CharField(source="conversation.summary", read_only=True, default="")
    requirement = serializers.JSONField(source="conversation.requirement", read_only=True, default=dict)
    sentiment = serializers.CharField(source="conversation.sentiment", read_only=True, default="")
    intent_score = serializers.IntegerField(source="conversation.intent_score", read_only=True, default=None)
    outcome = serializers.CharField(source="conversation.outcome", read_only=True, default="")
    follow_up_required = serializers.BooleanField(
        source="conversation.follow_up_required", read_only=True, default=False
    )

    class Meta(CallSerializer.Meta):
        fields = CallSerializer.Meta.fields + [
            "metrics",
            "events",
            "summary",
            "requirement",
            "sentiment",
            "intent_score",
            "outcome",
            "follow_up_required",
        ]
        read_only_fields = fields


class CallViewSet(TenantContextMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_permissions(self):
        key = "calls.make" if self.action in ("create", "cancel", "schedule") else "calls.view"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_serializer_class(self):
        return CallDetailSerializer if self.action == "retrieve" else CallSerializer

    def get_queryset(self):
        qs = Call.objects.filter(company=self.request.company).select_related("employee", "lead", "conversation")
        params = self.request.query_params
        for key, field in (
            ("direction", "direction"),
            ("status", "status"),
            ("employee", "employee_id"),
            ("lead", "lead_id"),
            ("reason", "reason"),
        ):
            if params.get(key):
                qs = qs.filter(**{field: params[key]})
        return qs

    def _pick(self, data):
        company = self.request.company
        employee = AIEmployee.objects.filter(company=company, pk=data.get("employee")).first()
        lead = Lead.objects.filter(company=company, pk=data.get("lead"), deleted_at__isnull=True).first()
        if not employee:
            raise ValidationError({"employee": "Choose an AI Employee."})
        if not lead:
            raise ValidationError({"lead": "Choose a lead."})
        return employee, lead

    def create(self, request, *args, **kwargs):
        employee, lead = self._pick(request.data)
        call = _errors(services.place_call, employee, lead, "call_now", request.user, request._request)
        return Response(CallSerializer(call).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def schedule(self, request):
        employee, lead = self._pick(request.data)
        when = parse_datetime(str(request.data.get("at") or ""))
        if not when:
            raise ValidationError({"at": "Give the date and time (ISO 8601)."})
        call = services.schedule_follow_up(employee, lead, when, request.user)
        return Response(CallSerializer(call).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        call = _errors(services.cancel, self.get_object(), request.user, request._request)
        return Response(CallSerializer(call).data)


class CallingPolicyView(TenantContextMixin, APIView):
    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("phone_numbers.manage")()]

    def get(self, request):
        return Response({"effective": services.policy(request.company), "own": _own(request.company)})

    def put(self, request):
        effective = _errors(services.save_policy, request.company, request.data, request.user, request._request)
        return Response({"effective": effective, "own": _own(request.company)})


def _own(company):
    return (company.settings or {}).get("calling") or {}


# ------------------------------------------------------------------ Super Admin: number pool (VOICE-16)
class AdminPhoneNumberSerializer(serializers.ModelSerializer):
    provider = serializers.CharField()
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    company = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    company_name = serializers.CharField(source="company.name", read_only=True, default="")
    employee_name = serializers.CharField(source="employee.name", read_only=True, default="")

    class Meta:
        model = PhoneNumber
        fields = [
            "id",
            "provider",
            "provider_name",
            "e164",
            "label",
            "provider_number_id",
            "capabilities",
            "company",
            "company_name",
            "employee_name",
            "is_test",
            "status",
        ]

    def to_representation(self, obj):
        out = super().to_representation(obj)
        out["provider"] = obj.provider.key
        out["company"] = str(obj.company_id) if obj.company_id else ""
        return out


class AdminPhoneNumberViewSet(AdminViewSet):
    view_perm = manage_perm = "number_pool.manage"
    serializer_class = AdminPhoneNumberSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return PhoneNumber.objects.select_related("provider", "company", "employee")

    def _out(self, number):
        return Response(AdminPhoneNumberSerializer(self.get_queryset().get(pk=number.pk)).data)

    def create(self, request, *args, **kwargs):
        number = _errors(services.save_number, None, dict(request.data), request.user, request._request)
        response = self._out(number)
        response.status_code = status.HTTP_201_CREATED
        return response

    def partial_update(self, request, *args, **kwargs):
        number = self.get_object()
        return self._out(_errors(services.save_number, number, dict(request.data), request.user, request._request))

    def destroy(self, request, *args, **kwargs):
        _errors(services.delete_number, self.get_object(), request.user, request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)
