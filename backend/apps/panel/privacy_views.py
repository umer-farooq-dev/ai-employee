"""Company panel: Settings → Data & privacy (TEN-07, COMP-09, CP-06): data export, account deletion, retention."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.storage import private_storage
from apps.platform_config.services import get as setting
from apps.tenancy import privacy
from apps.tenancy.models import DataRequest
from apps.tenancy.services import owners
from apps.voice.services import policy

from .company_views import _errors, company_perm


def _is_owner(request):
    return request.user.email in owners(request.company)


@company_perm("company.manage")
def privacy_page(request):
    company = request.company
    if request.method == "POST":
        op = request.POST.get("op")
        try:
            if op == "export":
                privacy.request_export(company, request.user, request)
                messages.success(request, "Your export is being prepared. We e-mail you when it is ready.")
            elif op in ("delete", "cancel"):
                if not _is_owner(request):
                    raise PermissionDenied
                if op == "delete":
                    req = privacy.request_deletion(
                        company, request.user, request.POST.get("confirm", ""), request.POST.get("reason", ""), request
                    )
                    messages.warning(
                        request, f"Deletion scheduled for {timezone.localtime(req.scheduled_for):%d %b %Y}."
                    )
                else:
                    req = get_object_or_404(DataRequest, pk=request.POST.get("request"), company=company)
                    privacy.cancel_deletion(req, request.user, request)
                    messages.success(request, "Deletion cancelled. Your account stays.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:privacy")
    rows = DataRequest.objects.filter(company=company).select_related("requested_by")[:20]
    return render(
        request,
        "panel/company/privacy.html",
        {
            "requests": rows,
            "scheduled": next((r for r in rows if r.kind == "deletion" and r.status == "scheduled"), None),
            "is_owner": _is_owner(request),
            "rules": policy(company),
            "grace_days": setting("privacy.deletion_grace_days"),
            "link_days": setting("privacy.export_link_days"),
        },
    )


@company_perm("company.manage")
def download(request, pk):
    req = get_object_or_404(DataRequest, pk=pk, company=request.company, kind=DataRequest.EXPORT)
    if req.status != DataRequest.READY or not req.file_key or (req.expires_at and req.expires_at < timezone.now()):
        raise Http404
    from apps.audit.services import record

    record(request, "privacy.export_download", "company", request.company.id, company=request.company,
           category="security")  # fmt: skip
    name = f"{request.company.slug}-export-{timezone.localtime(req.created_at):%Y%m%d}.zip"
    return FileResponse(private_storage.open(req.file_key, "rb"), as_attachment=True, filename=name)
