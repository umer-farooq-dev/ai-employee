"""Company panel: outbound calling campaigns (CAMP-01 … CAMP-06). Logic lives in apps.campaigns.services."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.agents.models import AIEmployee
from apps.campaigns import services as campaigns
from apps.campaigns.models import RETRY_OUTCOMES, WEEKDAYS, Campaign, CampaignMember
from apps.catalog.models import CatalogCollection
from apps.crm.models import Lead, SavedView
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm
from apps.voice.services import policy

from .company_views import _errors, company_perm


def _can(request, key):
    return has_perm(request.user, key, request.company)


@company_perm("campaigns.view")
def campaign_list(request):
    qs = Campaign.objects.select_related("employee")
    if request.GET.get("status") in dict(Campaign.STATUSES):
        qs = qs.filter(status=request.GET["status"])
    rows = [(c, campaigns.stats(c)) for c in qs]
    return render(
        request,
        "panel/company/campaigns/list.html",
        {
            "rows": rows,
            "statuses": Campaign.STATUSES,
            "status": request.GET.get("status", ""),
            "can_manage": _can(request, "campaigns.manage"),
        },
    )


@company_perm("campaigns.manage")
def campaign_form(request, pk=None):
    company = request.company
    campaign = get_object_or_404(Campaign, pk=pk) if pk else None
    if campaign and not campaign.editable:
        messages.error(request, "A finished campaign cannot be changed.")
        return redirect("panel:campaign", pk=campaign.pk)
    values = None
    if request.method == "POST":
        data = {
            **request.POST.dict(),
            "days": request.POST.getlist("days"),
            "retry_outcomes": request.POST.getlist("retry_outcomes"),
            "follow_up_labels": request.POST.getlist("follow_up_labels"),
        }
        try:
            campaign = campaigns.save_campaign(company, data, campaign, request.user, request)
            if pk is None and campaign.source != "leads":
                try:
                    added, no_phone = campaigns.build_list(campaign, request, request.FILES.get("file"))
                    messages.success(request, f"Campaign saved with {added} lead(s) in the list.")
                    if no_phone:
                        messages.warning(request, f"{no_phone} lead(s) have no phone number and were left out.")
                except ValidationError as exc:
                    messages.success(request, "Campaign saved.")
                    _errors(request, exc)
            else:
                messages.success(request, "Campaign saved.")
            return redirect("panel:campaign", pk=campaign.pk)
        except ValidationError as exc:
            _errors(request, exc)
            values = data
    if values is None:
        if campaign:
            values = {
                f: getattr(campaign, f)
                for f in (
                    "name",
                    "description",
                    "brief",
                    "source",
                    "filter_params",
                    "starts_on",
                    "ends_on",
                    "days",
                    "max_attempts",
                    "retry_gap_minutes",
                    "retry_outcomes",
                    "whatsapp_after_call",
                    "follow_up_labels",
                    "follow_up_after_days",
                    "max_concurrent",
                    "daily_limit",
                    "test_mode",
                )
            }
            values.update(
                employee=str(campaign.employee_id),
                saved_view=str(campaign.saved_view_id or ""),
                starts_on=campaign.starts_on.isoformat() if campaign.starts_on else "",
                ends_on=campaign.ends_on.isoformat() if campaign.ends_on else "",
                collection=str(campaign.collection_id or ""),
                windows=", ".join(f"{a}-{b}" for a, b in campaign.windows),
                test_numbers=", ".join(campaign.test_numbers),
            )
        else:
            d = campaigns.defaults(company)
            values = {
                **d,
                "windows": ", ".join(f"{a}-{b}" for a, b in d["windows"]),
                "source": request.GET.get("source", "filter"),
                "filter_params": request.GET.get("filters", ""),
            }
    rules = policy(company)
    return render(
        request,
        "panel/company/campaigns/form.html",
        {
            "campaign": campaign,
            "v": values,
            "employees": AIEmployee.objects.exclude(status=AIEmployee.ARCHIVED),
            "views": SavedView.objects.filter(user=request.user),
            "collections": CatalogCollection.objects.all(),
            "weekdays": WEEKDAYS,
            "outcomes": RETRY_OUTCOMES,
            "labels": Lead.SCORE_LABELS,
            "sources": Campaign.SOURCES,
            "rules": rules,
            "team": campaigns.team_phones(company),
            "max_test": setting("campaigns.max_test_numbers"),
        },
    )


@company_perm("campaigns.view")
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("employee", "collection", "saved_view"), pk=pk)
    if request.method == "POST":
        return _detail_post(request, campaign)
    members = campaign.members.select_related("lead", "last_call")
    show = request.GET.get("show", "")
    if show in dict(CampaignMember.STATUSES):
        members = members.filter(status=show)
    elif show in ("connected", "qualified", "hot", "appointment"):
        members = members.filter(**{show: True})
    return render(
        request,
        "panel/company/campaigns/detail.html",
        {
            "campaign": campaign,
            "stats": campaigns.stats(campaign),
            "stat_labels": campaigns.STAT_LABELS,
            "retry_labels": ", ".join(
                label.lower() for key, label in RETRY_OUTCOMES if key in (campaign.retry_outcomes or [])
            ),
            "page": Paginator(members.order_by("created_at"), 50).get_page(request.GET.get("page")),
            "show": show,
            "member_statuses": CampaignMember.STATUSES,
            "can": {
                "manage": _can(request, "campaigns.manage"),
                "approve": _can(request, "campaigns.approve"),
                "export": _can(request, "leads.export"),
            },
            "in_schedule": campaigns.in_schedule(campaign, timezone.now()),
        },
    )


def _detail_post(request, campaign):
    op = request.POST.get("op")
    need = "campaigns.approve" if op == "approve" else "campaigns.manage"
    if not _can(request, need):
        raise PermissionDenied
    try:
        if op == "build":
            added, no_phone = campaigns.build_list(campaign, request, request.FILES.get("file"))
            messages.success(request, f"The list now has {added} lead(s).")
            if no_phone:
                messages.warning(request, f"{no_phone} lead(s) have no phone number and were left out.")
        elif op == "remove" and campaign.status == Campaign.DRAFT:
            campaign.members.filter(pk=request.POST.get("member")).delete()
        elif op == "request_approval":
            campaigns.request_approval(campaign, request.user, request)
            messages.success(request, "Sent for approval: company admins were alerted.")
        elif op == "approve":
            campaigns.approve(campaign, request.user, request)
            messages.success(
                request,
                (
                    "Approved: calls start within a minute."
                    if campaign.status == Campaign.RUNNING
                    else f"Approved: calls start on {campaign.starts_on:%d %b %Y}."
                ),
            )
        elif op == "pause":
            campaigns.pause(campaign, request.user, request)
            messages.success(request, "Paused: calls already in progress finish; no new calls start.")
        elif op == "resume":
            campaigns.resume(campaign, request.user, request)
            messages.success(request, "Resumed.")
        elif op == "stop":
            campaigns.stop(campaign, request.POST.get("reason", ""), request.user, request)
            messages.success(request, "Stopped.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("panel:campaign", pk=campaign.pk)


@company_perm("leads.export")
def campaign_export(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if not _can(request, "campaigns.view"):
        raise PermissionDenied
    data, content_type, ext = campaigns.export(campaign, request.GET.get("format", "csv"), request.user, request)
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="campaign-{campaign.pk.hex[:8]}.{ext}"'
    return response
