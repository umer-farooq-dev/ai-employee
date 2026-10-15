"""REST API for industry templates (SA-05, IND-01 … IND-05), CRM configuration (SA-07), roles (ROLE-01), holidays.

Admin: /api/v1/admin/templates/…, …/template-fields/ etc. Company: /api/v1/company/template/ (current + update).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record
from apps.industries import services as templates
from apps.industries.models import (
    AppointmentType,
    CatalogType,
    FieldDefinition,
    Holiday,
    LeadSource,
    LeadStatus,
    ScoringRule,
    TemplateVersion,
)
from apps.roles_tools.models import EmployeeRole

from .base import AdminViewSet, TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


def _serializer(model_, fields_):
    class S(serializers.ModelSerializer):
        class Meta:
            model = model_
            fields = fields_

    S.__name__ = f"{model_.__name__}Serializer"
    return S


TemplateVersionSerializer = _serializer(
    TemplateVersion,
    [
        "id",
        "industry",
        "version",
        "status",
        "notes",
        "base_instructions",
        "qualification_flow",
        "handoff_rules",
        "greetings",
        "disclosure_texts",
        "default_faqs",
        "whatsapp_templates",
        "enabled_tools",
        "status_transitions",
        "score_thresholds",
        "published_at",
    ],
)
CHILD = ["id", "template_version", "sort_order"]
FieldSerializer = _serializer(
    FieldDefinition,
    CHILD
    + [
        "entity",
        "key",
        "label",
        "type",
        "options",
        "required",
        "ai_extractable",
        "extraction_hint",
        "filterable",
        "show_in_list",
        "help_text",
        "validation",
        "is_active",
    ],
)
CatalogTypeSerializer = _serializer(CatalogType, CHILD + ["key", "name", "item_label", "match_rules", "display"])
AppointmentTypeSerializer = _serializer(
    AppointmentType,
    CHILD + ["key", "name", "duration_min", "buffer_min", "location_mode", "reminder_offsets", "is_active"],
)
LeadStatusSerializer = _serializer(LeadStatus, CHILD + ["key", "label", "color", "category", "is_system"])
ScoringRuleSerializer = _serializer(
    ScoringRule, CHILD + ["key", "name", "condition", "points", "force_label", "priority", "is_active"]
)


class TemplateVersionViewSet(AdminViewSet):
    """List / read versions; PATCH a draft; POST draft / publish (publishing an archived version = rollback)."""

    serializer_class = TemplateVersionSerializer
    view_perm = manage_perm = "industries.manage"
    pagination_class = None
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        qs = TemplateVersion.objects.select_related("industry")
        if self.request.query_params.get("industry"):
            qs = qs.filter(industry_id=self.request.query_params["industry"])
        return qs

    def create(self, request, *args, **kwargs):
        """New draft: {"industry": id, "from_version": id (optional)}."""
        from apps.industries.models import Industry

        industry = get_object_or_404(Industry, pk=request.data.get("industry"))
        source = industry.versions.filter(pk=request.data.get("from_version")).first()
        draft = _errors(templates.create_draft, industry, source, request.user, request=request._request)
        return Response(TemplateVersionSerializer(draft).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        if not serializer.instance.editable:
            raise ValidationError("Only drafts can be changed.")
        serializer.save()
        record(self.request, "template.update", "template_version", serializer.instance.id)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        version = _errors(templates.publish, self.get_object(), request.user, request=request._request)
        return Response(TemplateVersionSerializer(version).data)


def _child_viewset(model_, serializer_):
    class ChildViewSet(AdminViewSet):
        serializer_class = serializer_
        view_perm = manage_perm = "industries.manage"
        pagination_class = None

        def get_queryset(self):
            qs = model_.objects.filter(company__isnull=True, template_version__isnull=False)
            if self.request.query_params.get("version"):
                qs = qs.filter(template_version_id=self.request.query_params["version"])
            return qs

        def _check(self, version):
            if not version or not version.editable:
                raise ValidationError("Only draft versions can be changed.")

        def perform_create(self, serializer):
            self._check(serializer.validated_data.get("template_version"))
            serializer.save()

        def perform_update(self, serializer):
            self._check(serializer.instance.template_version)
            serializer.save()

        def perform_destroy(self, instance):
            self._check(instance.template_version)
            instance.delete()

    ChildViewSet.__name__ = f"{model_.__name__}AdminViewSet"
    return ChildViewSet


TemplateFieldViewSet = _child_viewset(FieldDefinition, FieldSerializer)
TemplateCatalogTypeViewSet = _child_viewset(CatalogType, CatalogTypeSerializer)
TemplateAppointmentTypeViewSet = _child_viewset(AppointmentType, AppointmentTypeSerializer)
TemplateStatusViewSet = _child_viewset(LeadStatus, LeadStatusSerializer)
TemplateScoringViewSet = _child_viewset(ScoringRule, ScoringRuleSerializer)


def _platform_viewset(model_, fields_, perm_key, filters=None):
    class PlatformViewSet(AdminViewSet):
        serializer_class = _serializer(model_, fields_)
        view_perm = manage_perm = perm_key
        pagination_class = None

        def get_queryset(self):
            return model_.objects.filter(**(filters or {}))

        def perform_destroy(self, instance):
            if getattr(instance, "is_system", False):
                raise ValidationError("Seeded statuses cannot be deleted.")
            instance.delete()

    PlatformViewSet.__name__ = f"{model_.__name__}PlatformViewSet"
    return PlatformViewSet


DefaultStatusViewSet = _platform_viewset(
    LeadStatus,
    ["id", "key", "label", "color", "category", "sort_order", "is_system"],
    "crm_config.manage",
    {"template_version__isnull": True, "company__isnull": True},
)
LeadSourceViewSet = _platform_viewset(
    LeadSource, ["id", "key", "label", "is_active", "sort_order"], "crm_config.manage"
)
HolidayViewSet = _platform_viewset(Holiday, ["id", "date", "name", "region"], "holidays.manage")
EmployeeRoleViewSet = _platform_viewset(
    EmployeeRole,
    [
        "id",
        "key",
        "name",
        "description",
        "icon",
        "instructions",
        "allowed_channels",
        "allowed_tools",
        "default_rules",
        "plan_keys",
        "industries",
        "is_active",
        "sort_order",
    ],
    "employee_roles.manage",
)


class CompanyTemplateView(TenantContextMixin, APIView):
    """GET: the company's template version and any available update. POST: accept the update (IND-03)."""

    def get_permissions(self):
        key = "company.view" if self.request.method in permissions.SAFE_METHODS else "company.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def _data(self, company):
        current, update = company.template_version, templates.update_available(company)
        return {
            "industry": company.industry.key if company.industry else None,
            "version": current.version if current else None,
            "update_available": {"version": update.version, "notes": update.notes} if update else None,
        }

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(self._data(request.company))

    @extend_schema(request=None, responses=dict)
    def post(self, request):
        update = templates.update_available(request.company)
        if not update:
            raise ValidationError("No update available.")
        _errors(templates.assign_version, request.company, update, request=request._request)
        return Response(self._data(request.company))
