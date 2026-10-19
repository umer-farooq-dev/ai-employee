"""REST API for WhatsApp (M15).

Company (/api/v1/whatsapp/):
  numbers/                       list;  numbers/<id>/  PATCH {"employee"}  (connect to an AI Employee)
  templates/                     list (?status=, ?purpose=), create;  templates/<id>/  read, update (drafts), delete
  templates/<id>/submit/         POST (multipart "sample" for an image / PDF header)
  templates/sync/                POST — approval status from Meta
  templates/library/             GET the platform library;  templates/from-library/  POST {default, number, language}
  send/                          POST {lead, template, item?, appointment?, text?} — an approved template to a lead
  messages/                      ?lead=&conversation= — delivery log
Admin (/api/v1/admin/): whatsapp-numbers/ (pool) · whatsapp-library/ (default templates)
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AIEmployee
from apps.catalog.models import CatalogItem
from apps.crm.models import Lead
from apps.rbac.services import has_perm
from apps.scheduling.models import Appointment
from apps.tenancy.context import platform_context
from apps.whatsapp import services as wa
from apps.whatsapp.models import DefaultTemplate, Template, WaMessage, WhatsAppNumber

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
class NumberSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True, default="")
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = WhatsAppNumber
        fields = ["id", "e164", "display_name", "employee", "employee_name", "provider_name", "is_test", "status"]
        read_only_fields = fields


class TemplateSerializer(serializers.ModelSerializer):
    number_e164 = serializers.CharField(source="number.e164", read_only=True)

    class Meta:
        model = Template
        fields = [
            "id",
            "number",
            "number_e164",
            "name",
            "language",
            "meta_language",
            "category",
            "purpose",
            "header_type",
            "header_text",
            "body",
            "footer",
            "buttons",
            "variables",
            "status",
            "rejected_reason",
            "provider_template_id",
            "synced_at",
            "updated_at",
        ]
        read_only_fields = fields


class DefaultTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultTemplate
        fields = [
            "id",
            "name",
            "title",
            "purpose",
            "category",
            "header_type",
            "texts",
            "variables",
            "buttons",
            "is_active",
            "sort_order",
        ]

    def validate(self, data):
        merged = {**({} if self.instance is None else DefaultTemplateSerializer(self.instance).data), **data}
        _errors(wa.check_default, merged.get("name"), merged.get("texts"), merged.get("variables"))
        return data


class WaMessageSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True, default="")

    class Meta:
        model = WaMessage
        fields = [
            "id",
            "direction",
            "customer",
            "kind",
            "template_name",
            "status",
            "error",
            "category",
            "billable",
            "conversation",
            "lead",
            "created_at",
            "status_at",
        ]
        read_only_fields = fields


# ------------------------------------------------------------------ company
class NumberViewSet(TenantContextMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NumberSerializer
    pagination_class = None

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("whatsapp.manage")()]

    def get_queryset(self):
        return wa.numbers_for(self.request.company)

    def partial_update(self, request, pk=None):
        number = next((n for n in self.get_queryset() if str(n.pk) == str(pk)), None)
        if number is None:
            raise ValidationError("Unknown number.")
        employee = None
        if request.data.get("employee"):
            employee = get_object_or_404(AIEmployee, pk=request.data["employee"], company=request.company)
        number = _errors(wa.connect_number, request.company, number, employee, request.user, request._request)
        return Response(NumberSerializer(number).data)


class TemplateViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = TemplateSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        read = self.request.method in permissions.SAFE_METHODS and self.action != "library"
        return [permissions.IsAuthenticated(), perm("whatsapp.send" if read else "whatsapp.manage")()]

    def get_queryset(self):
        qs = Template.objects.filter(company=self.request.company).select_related("number")
        for key in ("status", "purpose", "language"):
            if self.request.query_params.get(key):
                qs = qs.filter(**{key: self.request.query_params[key]})
        return qs

    def create(self, request, *args, **kwargs):
        t = _errors(wa.save_template, request.company, None, request.data, request.user, request._request)
        return Response(TemplateSerializer(t).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        t = _errors(wa.save_template, request.company, self.get_object(), request.data, request.user, request._request)
        return Response(TemplateSerializer(t).data)

    def destroy(self, request, *args, **kwargs):
        _errors(wa.delete_template, self.get_object(), request.user, request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        upload = request.FILES.get("sample")
        sample = (upload.read(), upload.content_type) if upload else None
        t = _errors(wa.submit_template, self.get_object(), sample, request.user, request._request)
        return Response(TemplateSerializer(t).data)

    @action(detail=False, methods=["post"])
    def sync(self, request):
        changed = _errors(wa.sync_templates, request.company)
        return Response({"changed": changed, "templates": TemplateSerializer(self.get_queryset(), many=True).data})

    @action(detail=False, methods=["get"])
    def library(self, request):
        return Response(DefaultTemplateSerializer(wa.library(), many=True).data)

    @action(detail=False, methods=["post"], url_path="from-library")
    def from_library(self, request):
        default = get_object_or_404(DefaultTemplate, pk=request.data.get("default"), is_active=True)
        number = next(
            (n for n in wa.numbers_for(request.company) if str(n.pk) == str(request.data.get("number"))), None
        )
        if number is None:
            raise ValidationError({"number": "Choose one of your WhatsApp numbers."})
        t = _errors(
            wa.copy_default, request.company, default, number, request.data.get("language", ""), request.user, request
        )
        return Response(TemplateSerializer(t).data, status=status.HTTP_201_CREATED)


def template_context(request):
    """Lead, item and appointment named in a send request, looked up inside the company only."""
    company, data = request.company, request.data
    ctx = {"text": str(data.get("text") or "")[:500]}
    if data.get("item"):
        ctx["item"] = get_object_or_404(CatalogItem, pk=data["item"], company=company)
    if data.get("appointment"):
        ctx["appointment"] = get_object_or_404(
            Appointment.objects.select_related("appointment_type"), pk=data["appointment"], company=company
        )
    return ctx


class SendView(TenantContextMixin, APIView):
    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("whatsapp.send")()]

    @extend_schema(request=dict, responses=WaMessageSerializer)
    def post(self, request):
        lead = get_object_or_404(Lead, pk=request.data.get("lead"), company=request.company, deleted_at__isnull=True)
        template = get_object_or_404(
            Template.objects.select_related("number"), pk=request.data.get("template"), company=request.company
        )
        row = _errors(wa.send_template, template, lead, template_context(request), request.user, None, request._request)
        return Response(WaMessageSerializer(row).data, status=status.HTTP_201_CREATED)


class MessageViewSet(TenantContextMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = WaMessageSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("whatsapp.send")()]

    def get_queryset(self):
        qs = WaMessage.objects.filter(company=self.request.company).select_related("template")
        for key in ("lead", "conversation", "status", "direction"):
            if self.request.query_params.get(key):
                qs = qs.filter(**{key: self.request.query_params[key]})
        return qs


# ------------------------------------------------------------------ Super Admin
class AdminNumberSerializer(serializers.ModelSerializer):
    provider = serializers.CharField()
    company = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    company_name = serializers.CharField(source="company.name", read_only=True, default="")
    employee_name = serializers.CharField(source="employee.name", read_only=True, default="")

    class Meta:
        model = WhatsAppNumber
        fields = [
            "id",
            "provider",
            "e164",
            "display_name",
            "phone_number_id",
            "waba_id",
            "company",
            "company_name",
            "employee_name",
            "is_test",
            "status",
            "quality",
        ]
        read_only_fields = ["quality"]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        data["provider"], data["company"] = obj.provider.key, str(obj.company_id or "")
        return data


class AdminNumberViewSet(AdminViewSet):
    serializer_class = AdminNumberSerializer
    view_perm = manage_perm = "number_pool.manage"
    pagination_class = None

    def get_queryset(self):
        with platform_context():
            return WhatsAppNumber.objects.select_related("provider", "company", "employee")

    def create(self, request, *args, **kwargs):
        number = _errors(wa.save_number, None, dict(request.data), request.user, request._request)
        return Response(AdminNumberSerializer(number).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        number = _errors(wa.save_number, self.get_object(), dict(request.data), request.user, request._request)
        return Response(AdminNumberSerializer(number).data)

    update = partial_update


class AdminLibraryViewSet(AdminViewSet):
    serializer_class = DefaultTemplateSerializer
    view_perm = manage_perm = "whatsapp_templates.manage"
    pagination_class = None
    queryset = DefaultTemplate.objects.all()
