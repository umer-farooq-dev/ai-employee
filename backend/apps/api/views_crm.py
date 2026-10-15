"""REST API for the CRM (CRM-01 … CRM-18, SCORE-02, CP-04). /api/v1/crm/…

Visibility and permissions match the panel: agents see their own leads, leads.view_all sees everything.
Writes go through apps.crm.services, so the API and the panel behave the same.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import filters, imports
from apps.crm import services as crm
from apps.crm.models import AssignmentRule, Lead, LeadActivity, LeadImport, LeadNote, Task
from apps.industries import services as templates
from apps.industries.models import FieldDefinition, LeadSource, ScoringRule
from apps.rbac.services import has_perm

from .base import TenantContextMixin, perm
from .views_templates import FieldSerializer, LeadStatusSerializer, ScoringRuleSerializer


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except crm.DuplicateLead as exc:
        raise ValidationError({"detail": exc.messages, "duplicate_id": str(exc.lead.pk)}) from None
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


def _need(request, key):
    if not has_perm(request.user, key, request.company):
        raise PermissionDenied(f"Missing permission: {key}")


class LeadSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    status = serializers.CharField(source="status.key", read_only=True)
    status_label = serializers.CharField(source="status.label", read_only=True)
    source = serializers.SlugRelatedField(slug_field="key", read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id",
            "reference",
            "number",
            "name",
            "phone",
            "email",
            "source",
            "status",
            "status_label",
            "score_label",
            "score_value",
            "score_reason",
            "assigned_user",
            "assigned_ai_employee_id",
            "preferred_language",
            "tags",
            "custom",
            "consent_status",
            "dnd",
            "follow_up_at",
            "last_contact_at",
            "next_action",
            "created_via",
            "created_at",
            "updated_at",
            "deleted_at",
        ]
        read_only_fields = fields


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadActivity
        fields = ["id", "type", "summary", "data", "actor_type", "actor", "created_at"]


class NoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadNote
        fields = ["id", "body", "author", "created_at"]


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id",
            "lead",
            "assigned_user",
            "type",
            "title",
            "notes",
            "due_at",
            "status",
            "completed_at",
            "created_at",
        ]
        read_only_fields = ["status", "completed_at", "created_at"]


class LeadViewSet(TenantContextMixin, viewsets.ReadOnlyModelViewSet):
    """GET list supports the same filters as the panel (q, status, score, source, assignee, follow_up, tag,
    created_from/to, deleted, sort, cf_<field>)."""

    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated, perm("leads.view")]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        if self.action == "list":
            return filters.apply(self.request, self.request.query_params)[0]
        return crm.visible(self.request, include_deleted=True)

    def _lead(self):
        return self.get_object()

    def create(self, request):
        _need(request, "leads.manage")
        data = dict(request.data)
        if not has_perm(request.user, "leads.assign", request.company):
            data.pop("assigned_user", None)
            if not has_perm(request.user, "leads.view_all", request.company):
                data["assigned_user"] = request.user.pk
        lead = _errors(
            crm.create_lead, request.company, data, request.user, created_via="api", request=request._request
        )
        return Response(LeadSerializer(lead).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        _need(request, "leads.manage")
        data = dict(request.data)
        if "assigned_user" in data:
            _need(request, "leads.assign")
        lead = _errors(crm.update_lead, self._lead(), data, request.user, request=request._request)
        return Response(LeadSerializer(lead).data)

    def destroy(self, request, pk=None):
        _need(request, "leads.delete")
        crm.soft_delete(self._lead(), request.user, request=request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        _need(request, "leads.delete")
        lead = self._lead()
        _errors(crm.restore, lead, request.user, request=request._request)
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=dict, responses=LeadSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        _need(request, "leads.manage")
        lead = _errors(
            crm.set_status, self._lead(), request.data.get("status", ""), request.user, request=request._request
        )
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=dict, responses=LeadSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        _need(request, "leads.assign")
        lead = _errors(
            crm.assign, self._lead(), request.data.get("user") or None, request.user, request=request._request
        )
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=dict, responses=LeadSerializer)
    @action(detail=True, methods=["post"], url_path="follow-up")
    def follow_up(self, request, pk=None):
        _need(request, "leads.manage")
        lead = _errors(
            crm.schedule_follow_up,
            self._lead(),
            request.data.get("when"),
            request.data.get("next_action", ""),
            request.user,
            request=request._request,
        )
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        lead = self._lead()
        if request.method == "POST":
            _need(request, "leads.manage")
            note = _errors(crm.add_note, lead, request.data.get("body"), request.user, request=request._request)
            return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)
        return Response(NoteSerializer(lead.notes.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        return Response(ActivitySerializer(self._lead().activities.all()[:500], many=True).data)

    @extend_schema(request=dict, responses=LeadSerializer)
    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """CRM-14: {"others": [lead ids]} are merged into this lead."""
        _need(request, "leads.delete")
        others = list(crm.visible(request).filter(pk__in=request.data.get("others") or []))
        lead = _errors(crm.merge, self._lead(), others, request.user, request=request._request)
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=dict, responses=dict)
    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """CRM-17: {"ids": [...], "action": "assign|status|tag|delete", "value": ...}."""
        need = {"assign": "leads.assign", "status": "leads.assign", "tag": "leads.manage", "delete": "leads.delete"}
        _need(request, need.get(request.data.get("action"), "leads.assign"))
        leads = crm.visible(request).filter(pk__in=request.data.get("ids") or [])
        count = _errors(
            crm.bulk,
            request.company,
            leads,
            request.data.get("action"),
            request.data.get("value"),
            request.user,
            request._request,
        )
        return Response({"updated": count})

    @action(detail=False, methods=["get"])
    def export(self, request):
        _need(request, "leads.export")
        qs = filters.apply(request, request.query_params)[0]
        data, content_type, ext = _errors(
            crm.export, request.company, qs, request.query_params.get("format", "csv"), request.user, request._request
        )
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="leads-{timezone.localdate():%Y%m%d}.{ext}"'
        return response

    @action(detail=False, methods=["get"])
    def duplicates(self, request):
        _need(request, "leads.delete")
        return Response(
            [
                {"key": g["key"], "leads": LeadSerializer(g["leads"], many=True).data}
                for g in crm.duplicate_groups(request.company)
            ]
        )

    @action(detail=False, methods=["get"])
    def search(self, request):
        """CP-04 global search by name, phone, email or lead ID."""
        return Response(LeadSerializer(crm.search(request, request.query_params.get("q"), 20), many=True).data)


class LeadImportView(TenantContextMixin, APIView):
    """POST multipart file → {id, headers, mapping, targets}; POST {mapping, duplicate_mode} to /<id>/ runs it."""

    permission_classes = [permissions.IsAuthenticated, perm("leads.import")]
    parser_classes = [MultiPartParser, JSONParser]

    def _data(self, imp):
        return {
            "id": imp.id,
            "status": imp.status,
            "headers": imp.headers,
            "mapping": imp.mapping,
            "total": imp.total,
            "created": imp.created,
            "updated": imp.updated,
            "skipped": imp.skipped,
            "failed": imp.failed,
            "errors": imp.errors[:200],
            "targets": imports.targets(imp.company),
        }

    @extend_schema(request=dict, responses=dict)
    def post(self, request, pk=None):
        if pk is None:
            if not request.FILES.get("file"):
                raise ValidationError({"file": "Required."})
            imp = _errors(imports.start, request.company, request.FILES["file"], request.user, request._request)
            return Response(self._data(imp), status=status.HTTP_201_CREATED)
        imp = get_object_or_404(LeadImport, pk=pk)
        if imp.status != LeadImport.PENDING:
            raise ValidationError("This import has already run.")
        imp = _errors(
            imports.run,
            imp,
            request.data.get("mapping") or {},
            request.data.get("duplicate_mode", "skip"),
            request.user,
            request._request,
        )
        return Response(self._data(imp))

    @extend_schema(responses=dict)
    def get(self, request, pk=None):
        return Response(self._data(get_object_or_404(LeadImport, pk=pk)))


class TaskViewSet(TenantContextMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """CRM-16. ?all=1 (leads.view_all) lists everyone's tasks; default = mine. ?due=today for today + overdue."""

    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated, perm("leads.view")]

    def get_queryset(self):
        qs = Task.objects.filter(status=Task.OPEN)
        if not (
            self.request.query_params.get("all") == "1"
            and has_perm(self.request.user, "leads.view_all", self.request.company)
        ):
            qs = qs.filter(assigned_user=self.request.user)
        if self.request.query_params.get("due") == "today":
            qs = qs.filter(due_at__date__lte=timezone.localdate())
        return qs

    def perform_create(self, serializer):
        _need(self.request, "leads.manage")
        data = dict(serializer.validated_data)
        lead = data.get("lead")
        if lead and not crm.visible(self.request).filter(pk=lead.pk).exists():
            raise PermissionDenied
        serializer.instance = _errors(
            crm.create_task, self.request.company, data, self.request.user, request=self.request._request
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = get_object_or_404(Task, pk=pk)
        if task.assigned_user_id != request.user.id and not has_perm(request.user, "leads.view_all", request.company):
            raise PermissionDenied
        crm.complete_task(task, request.user)
        return Response(TaskSerializer(task).data)


class CrmConfigView(TenantContextMixin, APIView):
    """What the company's CRM uses: statuses, sources, lead fields (template + own), scoring rules in effect."""

    permission_classes = [permissions.IsAuthenticated, perm("leads.view")]

    @extend_schema(responses=dict)
    def get(self, request):
        company = request.company
        return Response(
            {
                "statuses": LeadStatusSerializer(templates.statuses(company), many=True).data,
                "sources": [{"key": s.key, "label": s.label} for s in LeadSource.objects.filter(is_active=True)],
                "lead_fields": FieldSerializer(templates.fields_for(company, "lead"), many=True).data,
                "scoring_rules": ScoringRuleSerializer(templates.scoring_rules(company), many=True).data,
                "score_thresholds": templates.thresholds(company),
            }
        )


class _CompanyConfigViewSet(TenantContextMixin, viewsets.ModelViewSet):
    """Company-owned configuration rows (crm.configure)."""

    permission_classes = [permissions.IsAuthenticated, perm("crm.configure")]
    pagination_class = None
    model = None

    def get_queryset(self):
        return self.model.objects.filter(company=self.request.company)

    def perform_create(self, serializer):
        serializer.save(company=self.request.company)


class CompanyFieldViewSet(_CompanyConfigViewSet):
    serializer_class = FieldSerializer
    model = FieldDefinition

    def perform_create(self, serializer):
        company = self.request.company
        limit = crm.custom_field_limit(company)
        if limit is not None and FieldDefinition.objects.filter(company=company).count() >= limit:
            raise ValidationError(f"Your plan allows {limit} custom fields.")
        key = serializer.validated_data["key"]
        if key in {d.key for d in templates.fields_for(company, "lead")}:
            raise ValidationError("This key is already used by another lead field.")
        serializer.save(company=company, template_version=None, entity="lead")


class CompanyScoringRuleViewSet(_CompanyConfigViewSet):
    """SCORE-02: a company rule with the key of an industry rule replaces it."""

    serializer_class = ScoringRuleSerializer
    model = ScoringRule

    def perform_create(self, serializer):
        serializer.save(company=self.request.company, template_version=None)


class AssignmentRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssignmentRule
        fields = ["id", "name", "condition", "strategy", "targets", "priority", "is_active"]

    def validate_targets(self, value):
        company = self.context["request"].company
        member_ids = {str(u.pk) for u in crm.members(company)}
        if not value or any(str(v) not in member_ids for v in value):
            raise serializers.ValidationError("Targets must be active members of your team.")
        return [str(v) for v in value]


class AssignmentRuleViewSet(_CompanyConfigViewSet):
    serializer_class = AssignmentRuleSerializer
    model = AssignmentRule
