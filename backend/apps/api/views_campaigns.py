"""REST API for outbound calling campaigns (CAMP-01 … CAMP-06): /api/v1/campaigns/…

campaigns/                        GET (?status=) · POST {name, employee, brief, source, filter_params, saved_view,
                                  starts_on, ends_on, days, windows, max_attempts, retry_gap_minutes, retry_outcomes,
                                  collection, whatsapp_after_call, follow_up_labels, follow_up_after_days,
                                  max_concurrent, daily_limit, test_mode, test_numbers}
campaigns/<id>/                   GET · PATCH (draft / scheduled / paused) · DELETE (draft)
campaigns/<id>/build/             POST — (re)build the list from its source (multipart "file" for CSV) or
                                  {"lead_ids": [...]} to add picked leads
campaigns/<id>/request-approval/  POST · approve/ (campaigns.approve) · pause/ · resume/ · stop/ {reason}
campaigns/<id>/progress/          GET {status, waiting_reason, stats}
campaigns/<id>/members/           GET ?status= — per-lead results
campaigns/<id>/export/            GET ?format=csv|xlsx (leads.export)
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.campaigns import services as campaigns
from apps.campaigns.models import Campaign, CampaignMember
from apps.crm import services as crm
from apps.rbac.services import has_perm

from .base import TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class CampaignSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "description",
            "brief",
            "employee",
            "employee_name",
            "source",
            "filter_params",
            "saved_view",
            "starts_on",
            "ends_on",
            "days",
            "windows",
            "max_attempts",
            "retry_gap_minutes",
            "retry_outcomes",
            "collection",
            "whatsapp_after_call",
            "follow_up_labels",
            "follow_up_after_days",
            "max_concurrent",
            "daily_limit",
            "test_mode",
            "test_numbers",
            "status",
            "approval_requested_at",
            "approved_by",
            "approved_at",
            "started_at",
            "finished_at",
            "stop_reason",
            "waiting_reason",
            "created_at",
            "stats",
        ]
        read_only_fields = fields

    def get_stats(self, obj):
        return campaigns.stats(obj)


class MemberSerializer(serializers.ModelSerializer):
    lead_reference = serializers.CharField(source="lead.reference", default="", read_only=True)

    class Meta:
        model = CampaignMember
        fields = [
            "id",
            "lead",
            "lead_reference",
            "name",
            "phone",
            "status",
            "attempts",
            "next_attempt_at",
            "last_call",
            "last_called_at",
            "outcome",
            "connected",
            "qualified",
            "hot",
            "appointment",
            "summary",
            "skip_reason",
            "created_at",
        ]
        read_only_fields = fields


class CampaignViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    http_method_names = ["get", "post", "patch", "delete"]

    def get_permissions(self):
        key = "campaigns.view" if self.request.method in permissions.SAFE_METHODS else "campaigns.manage"
        if self.action == "approve":
            key = "campaigns.approve"
        if self.action == "export":
            key = "leads.export"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_queryset(self):
        qs = Campaign.objects.select_related("employee")
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @extend_schema(request=dict, responses=CampaignSerializer)
    def create(self, request):
        campaign = _errors(campaigns.save_campaign, request.company, request.data, None, request.user, request._request)
        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=dict, responses=CampaignSerializer)
    def partial_update(self, request, pk=None):
        campaign = self.get_object()
        data = {**CampaignSerializer(campaign).data, **request.data}
        data.update(
            employee=request.data.get("employee", str(campaign.employee_id)),
            windows=request.data.get("windows", campaign.windows),
        )
        campaign = _errors(campaigns.save_campaign, request.company, data, campaign, request.user, request._request)
        return Response(CampaignSerializer(campaign).data)

    def update(self, request, *args, **kwargs):
        raise PermissionDenied("Use PATCH.")

    def destroy(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != Campaign.DRAFT:
            raise ValidationError("Only a draft can be deleted; stop a campaign instead.")
        campaign.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=dict, responses=dict)
    @action(detail=True, methods=["post"])
    def build(self, request, pk=None):
        campaign = self.get_object()
        if request.data.get("lead_ids"):
            leads = crm.visible(request._request).filter(pk__in=request.data.get("lead_ids"))
            added, no_phone = _errors(campaigns.add_leads, campaign, leads, request.user, request._request)
        else:
            added, no_phone = _errors(campaigns.build_list, campaign, request._request, request.FILES.get("file"))
        return Response({"added": added, "without_phone": no_phone, "stats": campaigns.stats(campaign)})

    def _do(self, fn, *args):
        campaign = self.get_object()
        _errors(fn, campaign, *args)
        campaign.refresh_from_db()
        return Response(CampaignSerializer(campaign).data)

    @extend_schema(request=None, responses=CampaignSerializer)
    @action(detail=True, methods=["post"], url_path="request-approval")
    def request_approval(self, request, pk=None):
        return self._do(campaigns.request_approval, request.user, request._request)

    @extend_schema(request=None, responses=CampaignSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._do(campaigns.approve, request.user, request._request)

    @extend_schema(request=None, responses=CampaignSerializer)
    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return self._do(campaigns.pause, request.user, request._request)

    @extend_schema(request=None, responses=CampaignSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._do(campaigns.resume, request.user, request._request)

    @extend_schema(request=dict, responses=CampaignSerializer)
    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        return self._do(campaigns.stop, request.data.get("reason", ""), request.user, request._request)

    @extend_schema(responses=dict)
    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None):
        campaign = self.get_object()
        return Response(
            {"status": campaign.status, "waiting_reason": campaign.waiting_reason, "stats": campaigns.stats(campaign)}
        )

    @extend_schema(responses=MemberSerializer(many=True))
    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        qs = self.get_object().members.select_related("lead")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs.order_by("-created_at"))
        return self.get_paginated_response(MemberSerializer(page, many=True).data)

    @extend_schema(responses=bytes)
    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        campaign = self.get_object()
        if not has_perm(request.user, "campaigns.view", request.company):
            raise PermissionDenied
        fmt = request.query_params.get("format", "csv")
        data, content_type, ext = campaigns.export(campaign, fmt, request.user, request._request)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="campaign-{campaign.pk.hex[:8]}.{ext}"'
        return response
