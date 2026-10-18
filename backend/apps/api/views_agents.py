"""REST API for AI Employees, the test console / conversations and the tool registry (EMP-*, ENG-*, TOOL-*, SA-08).

Company (/api/v1/):
  ai-employees/                       list (q, status), create            ai-employees/options/  wizard choices
  ai-employees/<id>/                  read, update (any wizard step), delete = archive
  ai-employees/<id>/activate|pause|test-passed|restore-version   POST;  versions|readiness  GET
  ai-employees/<id>/test-sessions/    POST → new test conversation (opening message included)
  conversations/                      list (employee, test, lead, status);  conversations/<id>/  transcript + tool log
  conversations/<id>/messages/        POST {"text"} → the AI reply;  conversations/<id>/end/  POST
Admin (/api/v1/admin/):
  tools/ (TOOL-01) · ai-employees/ (+ pause, release, change-role) · conversations/<id>/ · companies/<id>/ai-employee/
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents import runtime
from apps.agents import services as employees
from apps.agents import tools as toolkit
from apps.agents.models import AIEmployee, ConfigVersion, Conversation, Message, ToolInvocation
from apps.audit.services import record
from apps.industries.models import Industry
from apps.providers import languages
from apps.rbac.services import has_perm
from apps.roles_tools.models import Tool
from apps.scheduling.models import Resource
from apps.tenancy.context import company_context
from apps.tenancy.models import Company

from .base import AdminViewSet, TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


def _need(request, key):
    if not has_perm(request.user, key, request.company):
        raise PermissionDenied(f"Missing permission: {key}")


# ------------------------------------------------------------------ serializers
class EmployeeSerializer(serializers.ModelSerializer):
    industry_key = serializers.CharField(source="industry.key", read_only=True)
    industry_name = serializers.CharField(source="industry.name", read_only=True)
    role_key = serializers.CharField(source="role.key", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    test_passed = serializers.BooleanField(read_only=True)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = AIEmployee
        fields = [
            "id",
            "name",
            "industry",
            "industry_key",
            "industry_name",
            "role",
            "role_key",
            "role_name",
            "template_version",
            "avatar",
            "persona",
            "greetings",
            "primary_language",
            "languages",
            "voices",
            "rules",
            "qualification",
            "tools",
            "calendar_resources",
            "status",
            "config_version",
            "tested_version",
            "test_passed",
            "wizard_step",
            "activated_at",
            "paused_reason",
            "paused_by_platform",
            "created_at",
            "updated_at",
            "stats",
        ]
        read_only_fields = fields

    def get_stats(self, obj):
        return (self.context.get("stats") or {}).get(obj.pk) or employees.stats([obj])[obj.pk]


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigVersion
        fields = ["version", "changes", "changed_by", "changed_by_email", "created_at", "snapshot"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "language", "citations", "meta", "created_at"]


class ToolInvocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolInvocation
        fields = ["id", "tool_key", "input", "output", "status", "latency_ms", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    lead_reference = serializers.CharField(source="lead.reference", read_only=True, default="")

    class Meta:
        model = Conversation
        fields = [
            "id",
            "employee",
            "employee_name",
            "employee_version",
            "lead",
            "lead_reference",
            "channel",
            "direction",
            "is_test",
            "status",
            "language",
            "summary",
            "requirement",
            "sentiment",
            "intent",
            "intent_score",
            "intent_confidence",
            "outcome",
            "follow_up_required",
            "score_label_after",
            "tool_calls",
            "started_at",
            "ended_at",
        ]
        read_only_fields = fields


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    tool_invocations = ToolInvocationSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages", "tool_invocations"]
        read_only_fields = fields


# ------------------------------------------------------------------ company: AI Employees (EMP-01 … EMP-12)
class AIEmployeeViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        read = self.request.method in permissions.SAFE_METHODS
        return [permissions.IsAuthenticated(), perm("ai_employees.view" if read else "ai_employees.manage")()]

    def get_queryset(self):
        qs = AIEmployee.objects.filter(company=self.request.company).select_related("industry", "role")
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        elif params.get("archived") != "1":
            qs = qs.exclude(status=AIEmployee.ARCHIVED)
        if params.get("q"):
            qs = qs.filter(Q(name__icontains=params["q"]) | Q(role__name__icontains=params["q"]))
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.action == "list":
            page = list(self.paginate_queryset(self.get_queryset()) or [])
            ctx["stats"] = employees.stats(page)
        return ctx

    def create(self, request, *args, **kwargs):
        employee = _errors(employees.create_employee, request.company, request.data, request.user, request._request)
        return Response(EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        employee = _errors(employees.update_employee, self.get_object(), request.data, request.user, request._request)
        return Response(EmployeeSerializer(employee).data)

    def destroy(self, request, *args, **kwargs):
        employees.archive(self.get_object(), request.user, request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def options(self, request):
        """Wizard choices: industries, employee types for an industry (?industry=), languages, resources."""
        company = request.company
        industries = employees.industries()
        chosen = industries.filter(key=request.query_params.get("industry") or "").first() or company.industry
        return Response(
            {
                "industries": [
                    {"id": str(i.pk), "key": i.key, "name": i.name, "languages": i.supported_languages}
                    for i in industries
                ],
                "roles": [
                    {
                        "id": str(r.pk),
                        "key": r.key,
                        "name": r.name,
                        "description": r.description,
                        "channels": r.allowed_channels,
                    }
                    for r in (employees.roles_for(company, chosen) if chosen else [])
                ],
                "languages": [{"code": c, "name": n} for c, n in languages.choices()],
                "calendar_resources": [
                    {"id": str(r.pk), "name": r.name} for r in Resource.objects.filter(company=company, is_active=True)
                ],
                "wizard_steps": [{"key": k, "label": label} for k, label in employees.WIZARD_STEPS],
            }
        )

    @action(detail=True, methods=["get"])
    def tools(self, request, pk=None):
        employee = self.get_object()
        return Response(
            [
                {
                    "key": t.key,
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "enabled": employee.tools.get(t.key, True),
                }
                for t in toolkit.available(employee)
            ]
        )

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        return Response(VersionSerializer(self.get_object().versions.all()[:50], many=True).data)

    @action(detail=True, methods=["post"], url_path="restore-version")
    def restore_version(self, request, pk=None):
        employee = self.get_object()
        if not employee.versions.filter(version=request.data.get("version")).exists():
            raise ValidationError({"version": "Unknown version."})
        employee = _errors(
            employees.restore_version, employee, int(request.data["version"]), request.user, request._request
        )
        return Response(EmployeeSerializer(employee).data)

    @action(detail=True, methods=["get"])
    def readiness(self, request, pk=None):
        return Response(employees.readiness(self.get_object()))

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        employee = _errors(employees.activate, self.get_object(), request.user, request._request)
        return Response(EmployeeSerializer(employee).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        employee = _errors(
            employees.pause, self.get_object(), request.data.get("reason", ""), False, request.user, request._request
        )
        return Response(EmployeeSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="test-passed")
    def test_passed(self, request, pk=None):
        employee = _errors(employees.mark_tested, self.get_object(), request.user, request._request)
        return Response(EmployeeSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="test-sessions")
    def test_sessions(self, request, pk=None):
        """EMP-10 test console: optional customer {name, phone, language} to try returning-customer memory."""
        conv = _errors(runtime.start, self.get_object(), "test", request.data.get("customer") or {}, request.user)
        return Response(ConversationDetailSerializer(conv).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="voice-test")
    def voice_test(self, request, pk=None):
        """VOICE-19 / EMP-10: browser voice test → the signed Voice Gateway address to open with the microphone."""
        from apps.voice import services as voice

        call, url = _errors(
            voice.start_browser_test,
            self.get_object(),
            request.data.get("language", ""),
            request.user,
            request._request,
        )
        return Response({"call": str(call.pk), "url": url, "language": call.language}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="test-call")
    def test_call(self, request, pk=None):
        """EMP-10: the AI Employee calls the tester's own phone (default: the phone in their profile)."""
        from apps.voice import services as voice

        phone = request.data.get("phone") or request.user.phone
        call = _errors(voice.place_test_call, self.get_object(), phone, request.user, request._request)
        if call.status == "failed":
            return Response(
                {"error": {"code": "call_failed", "message": call.error}}, status=status.HTTP_502_BAD_GATEWAY
            )
        return Response({"call": str(call.pk), "to": call.to_e164}, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------- company: conversations (transcripts, KB-11, TOOL-14)
class ConversationViewSet(
    TenantContextMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    def get_permissions(self):
        key = "conversations.view"
        if self.action in ("messages", "end"):
            key = "ai_employees.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_serializer_class(self):
        return ConversationDetailSerializer if self.action == "retrieve" else ConversationSerializer

    def get_queryset(self):
        qs = Conversation.objects.filter(company=self.request.company).select_related("employee", "lead")
        params = self.request.query_params
        for key, field in (
            ("employee", "employee_id"),
            ("lead", "lead_id"),
            ("status", "status"),
            ("channel", "channel"),
        ):
            if params.get(key):
                qs = qs.filter(**{field: params[key]})
        if params.get("test") in ("0", "1"):
            qs = qs.filter(is_test=params["test"] == "1")
        if self.action == "retrieve":
            qs = qs.prefetch_related("messages", "tool_invocations")
        return qs

    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        conv = self.get_object()
        if not conv.is_test:
            raise ValidationError("Only test conversations can be typed into here.")
        msg = _errors(runtime.reply, conv, request.data.get("text", ""))
        conv.refresh_from_db()
        lead = conv.lead
        return Response(
            {
                "message": MessageSerializer(msg).data,
                "lead": (
                    {
                        "reference": lead.reference,
                        "name": lead.name,
                        "custom": lead.custom,
                        "score_label": lead.score_label,
                    }
                    if lead
                    else None
                ),
                "status": conv.status,
            }
        )

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        conv = _errors(runtime.end, self.get_object())
        return Response(ConversationDetailSerializer(conv).data)


# ------------------------------------------------------------------ admin: tool registry (TOOL-01, SA-06)
class ToolSerializer(serializers.ModelSerializer):
    handler = serializers.ChoiceField(choices=toolkit.HANDLER_CHOICES)
    industries = serializers.SlugRelatedField(
        slug_field="key", many=True, required=False, queryset=Industry.objects.all()
    )

    class Meta:
        model = Tool
        fields = [
            "id",
            "key",
            "name",
            "description",
            "category",
            "handler",
            "config",
            "input_schema",
            "side_effect",
            "timeout_ms",
            "industries",
            "role_keys",
            "is_active",
            "sort_order",
        ]

    def validate_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        return value


class ToolViewSet(AdminViewSet):
    serializer_class = ToolSerializer
    view_perm = manage_perm = "tools.manage"
    pagination_class = None
    queryset = Tool.objects.prefetch_related("industries")

    def perform_create(self, serializer):
        tool = serializer.save()
        record(self.request, "tool.save", "tool", tool.key, changes={"handler": tool.handler, "active": tool.is_active})

    perform_update = perform_create

    def perform_destroy(self, instance):
        record(self.request, "tool.delete", "tool", instance.key)
        instance.delete()


# ------------------------------------------------------------------ admin: AI Employees of all companies (SA-08)
class AdminEmployeeSerializer(EmployeeSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta(EmployeeSerializer.Meta):
        fields = EmployeeSerializer.Meta.fields + ["company", "company_name"]
        read_only_fields = fields


class AdminEmployeeViewSet(
    TenantContextMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = AdminEmployeeSerializer

    def get_permissions(self):
        read = self.request.method in permissions.SAFE_METHODS and self.action != "versions"
        return [permissions.IsAuthenticated(), perm("ai_oversight.view" if read else "ai_oversight.manage")()]

    def get_queryset(self):
        qs = AIEmployee.all_companies.select_related("company", "industry", "role")
        params = self.request.query_params
        if params.get("company"):
            qs = qs.filter(company_id=params["company"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("q"):
            qs = qs.filter(Q(name__icontains=params["q"]) | Q(company__name__icontains=params["q"]))
        return qs

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        return Response(VersionSerializer(self.get_object().versions.all()[:50], many=True).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        employee = self.get_object()
        with company_context(employee.company_id):
            employee = _errors(
                employees.pause,
                employee,
                request.data.get("reason") or "Paused by the platform",
                True,
                request.user,
                request._request,
            )
        return Response(AdminEmployeeSerializer(employee).data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        employee = self.get_object()
        with company_context(employee.company_id):
            employee = employees.release_platform_pause(employee, request._request)
        return Response(AdminEmployeeSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="change-role")
    def change_role(self, request, pk=None):
        employee = self.get_object()
        with company_context(employee.company_id):
            employee = _errors(
                employees.change_role, employee, request.data.get("role"), request.user, request._request
            )
        return Response(AdminEmployeeSerializer(employee).data)


class AdminConversationView(TenantContextMixin, APIView):
    """TOOL-14 / SA-08: transcript and tool log of any conversation for platform staff."""

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("ai_oversight.view")()]

    def get(self, request, pk):
        conv = get_object_or_404(
            Conversation.all_companies.select_related("employee", "lead").prefetch_related(
                "messages", "tool_invocations"
            ),
            pk=pk,
        )
        return Response(ConversationDetailSerializer(conv).data)


class AdminCompanyEmployeeView(TenantContextMixin, APIView):
    """EMP-14: one click to create the ready-made AI Employee for a company (again)."""

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("ai_oversight.manage")()]

    def post(self, request, pk):
        company = get_object_or_404(Company, pk=pk)
        employee = _errors(employees.create_from_template, company, request.user, request._request, True)
        if not employee:
            raise ValidationError("The company needs an active industry with a published template.")
        return Response(AdminEmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)
