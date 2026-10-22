"""TEN-07 / COMP-09 / SEC-12 / CP-06: full data export, account deletion after a grace period, and retention of logs,
alerts and transcripts. Grace and retention days are settings (System Settings → Data retention & privacy).

Deletion removes every company record (leads, conversations, calls, knowledge with its vectors, files and recordings),
releases its phone and WhatsApp numbers to the pool and removes users who belonged only to this company. Invoices,
payments and the subscription stay (tax law), with the buyer details already copied into each invoice. Backups age out
under the backup retention.
"""

import io
import json
import logging
import threading
import zipfile
from datetime import timedelta

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.audit.services import record
from apps.core.crypto import EncryptedTextField
from apps.platform_config.services import get as setting

from .context import company_context, platform_context
from .models import Company, DataRequest, Membership, TenantModel

logger = logging.getLogger(__name__)
RUN_INLINE = False  # tests
D = DataRequest
KEEP = {"billing.Subscription", "billing.Invoice", "billing.Payment", "billing.CreditAdjustment", "tenancy.DataRequest"}
OWN_ROWS = ("industries.FieldDefinition", "industries.CatalogType", "industries.AppointmentType",
            "industries.LeadStatus", "industries.ScoringRule")  # fmt: skip
POOL = ("voice.PhoneNumber", "whatsapp.WhatsAppNumber")


def _tenant_models():
    return [m for m in apps.get_models() if issubclass(m, TenantModel)]


def _rows(model, company):
    manager = model.all_companies if issubclass(model, TenantModel) else model.objects
    fields = [f for f in model._meta.concrete_fields if not isinstance(f, EncryptedTextField)]
    return list(manager.filter(company=company).values(*[f.attname for f in fields]))


def _files(prefix):
    from apps.core.storage import private_storage

    out, stack = [], [prefix]
    while stack:
        path = stack.pop()
        try:
            dirs, files = private_storage.listdir(path)
        except (FileNotFoundError, NotADirectoryError, OSError):
            continue
        stack += [f"{path}/{d}" for d in dirs]
        out += [f"{path}/{f}" for f in files]
    return out


def build_export(company):
    """ZIP: one JSON file per table (secrets left out) and every stored file of the company."""
    from apps.core.storage import private_storage

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        profile = {f.name: getattr(company, f.attname) for f in Company._meta.concrete_fields}
        z.writestr("company.json", json.dumps(profile, default=str, indent=2))
        with platform_context():
            for model in _tenant_models() + [apps.get_model(x) for x in OWN_ROWS + POOL]:
                rows = _rows(model, company)
                if rows:
                    z.writestr(f"data/{model._meta.label_lower}.json", json.dumps(rows, default=str, indent=1))
            users = Membership.all_companies.filter(company=company).values(
                "user__email", "user__full_name", "user__phone", "role__key", "status", "joined_at"
            )
            z.writestr("data/team.json", json.dumps(list(users), default=str, indent=1))
        for path in _files(f"tenants/{company.id}"):
            if "/exports/" in path:
                continue
            with private_storage.open(path, "rb") as fh:
                z.writestr("files/" + path.split(f"tenants/{company.id}/", 1)[1], fh.read())
        z.writestr(
            "README.txt",
            f"Data export of {company.name} ({timezone.now():%Y-%m-%d %H:%M} UTC).\n"
            "data/*.json: one file per table. files/: uploaded files, knowledge sources and call recordings.\n",
        )
    return buf.getvalue()


def _run_export(pk):
    from apps.core.storage import company_path, private_storage

    with platform_context():
        req = D.all_companies.select_related("company", "requested_by").get(pk=pk)
    company = req.company
    with company_context(company.id):
        try:
            data = build_export(company)
            key = private_storage.save(company_path(company.id, "exports", "export.zip"), ContentFile(data))
            req.file_key, req.file_size, req.status = key, len(data), D.READY
            req.expires_at = timezone.now() + timedelta(days=setting("privacy.export_link_days"))
            req.save()
            _mail_export(req)
        except Exception as exc:  # noqa: BLE001 — recorded on the request for the owner to see
            logger.exception("export failed for %s", company.pk)
            req.status, req.error = D.FAILED, str(exc)[:500]
            req.save(update_fields=["status", "error", "updated_at"])


def _mail_export(req):
    from django.conf import settings
    from django.urls import reverse

    from apps.notifications import services as mail

    if req.requested_by and req.requested_by.email:
        mail.send(
            "privacy/export_ready",
            req.requested_by.email,
            {
                "company_name": req.company.name,
                "url": settings.PUBLIC_BASE_URL.rstrip("/") + reverse("panel:privacy_download", args=[req.pk]),
                "expires": f"{timezone.localtime(req.expires_at):%d %b %Y}",
            },
        )


def request_export(company, user, request=None):
    if D.objects.filter(company=company, kind=D.EXPORT, status=D.PENDING).exists():
        raise ValidationError("An export is already being prepared.")
    req = D.objects.create(company=company, kind=D.EXPORT, requested_by=user)
    record(request, "privacy.export_request", "company", company.id, company=company, user=user, category="security")
    if RUN_INLINE:
        _run_export(req.pk)
    else:
        transaction.on_commit(lambda: threading.Thread(target=_run_export, args=(req.pk,), daemon=True).start())
    return req


def request_deletion(company, user, confirm, reason="", request=None):
    if confirm.strip().lower() != company.name.strip().lower():
        raise ValidationError("Type the company name exactly to confirm.")
    if D.objects.filter(company=company, kind=D.DELETION, status=D.SCHEDULED).exists():
        raise ValidationError("Deletion is already scheduled.")
    when = timezone.now() + timedelta(days=setting("privacy.deletion_grace_days"))
    req = D.objects.create(company=company, kind=D.DELETION, status=D.SCHEDULED, requested_by=user,
                           reason=reason[:500], scheduled_for=when)  # fmt: skip
    record(request, "privacy.deletion_request", "company", company.id, company=company, user=user, category="security")
    from apps.notifications import services as mail
    from apps.tenancy.services import owners

    for to in owners(company):
        mail.send("privacy/deletion_scheduled", to, {"company_name": company.name, "date": f"{when:%d %b %Y}"})
    return req


def cancel_deletion(req, user, request=None):
    if req.kind != D.DELETION or req.status != D.SCHEDULED:
        raise ValidationError("Nothing to cancel.")
    req.status, req.cancelled_by = D.CANCELLED, user
    req.save(update_fields=["status", "cancelled_by", "updated_at"])
    record(request, "privacy.deletion_cancel", "company", req.company_id, company=req.company, user=user,
           category="security")  # fmt: skip


def purge(company):
    """Delete everything of the company except the tax records; returns {table: rows}."""
    from apps.core.storage import private_storage

    removed = {}
    with platform_context():
        for label in POOL:  # numbers go back to the pool
            model = apps.get_model(label)
            changes = {"company": None, **({"employee": None} if hasattr(model, "employee") else {})}
            model.objects.filter(company=company).update(**changes)
        users = list(Membership.all_companies.filter(company=company).values_list("user_id", flat=True))
        models = [m for m in _tenant_models() if m._meta.label not in KEEP] + [apps.get_model(x) for x in OWN_ROWS]
        for _ in range(6):  # protected relations clear in a few rounds
            left = []
            for model in models:
                manager = model.all_companies if issubclass(model, TenantModel) else model.objects
                try:
                    n, per = manager.filter(company=company).delete()
                    for k, v in per.items():
                        removed[k] = removed.get(k, 0) + v
                except ProtectedError:
                    left.append(model)
            if not left:
                break
            models = left
        from django.contrib.auth import get_user_model

        lonely = get_user_model().objects.filter(pk__in=users, is_staff=False, memberships__isnull=True)
        removed["users"] = lonely.count()
        lonely.delete()
    for path in _files(f"tenants/{company.id}"):
        private_storage.delete(path)
    company.name = f"Deleted company {company.slug}"
    company.legal_name = company.email = company.phone = company.website = company.address = company.logo = ""
    company.settings, company.business_hours, company.holidays, company.onboarding = {}, {}, [], {}
    company.status, company.deleted_at = Company.CANCELLED, company.deleted_at or timezone.now()
    company.save()
    return removed


def run(now=None):
    """Daily: due deletions, expired export files, and log / alert / transcript retention (SEC-12)."""
    from apps.core.storage import private_storage

    now = now or timezone.now()
    out = {"deleted": 0, "exports_expired": 0}
    with platform_context():
        due = list(D.all_companies.filter(kind=D.DELETION, status=D.SCHEDULED, scheduled_for__lte=now))
        expired = list(D.all_companies.filter(kind=D.EXPORT, status=D.READY, expires_at__lte=now))
    for req in due:
        company = Company.objects.get(pk=req.company_id)
        try:
            removed = purge(company)
            with platform_context():
                D.all_companies.filter(pk=req.pk).update(status=D.DONE, completed_at=timezone.now())
            record(
                None, "privacy.deleted", "company", company.id, company=company, changes=removed, category="security"
            )
            out["deleted"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("deletion failed for %s", company.pk)
            with platform_context():
                D.all_companies.filter(pk=req.pk).update(status=D.FAILED, error=str(exc)[:500])
    for req in expired:
        if req.file_key and private_storage.exists(req.file_key):
            private_storage.delete(req.file_key)
        with platform_context():
            D.all_companies.filter(pk=req.pk).update(status=D.EXPIRED, file_key="")
        out["exports_expired"] += 1
    out.update(retention(now))
    return out


def retention(now=None):
    """SEC-12: platform logs and alerts older than the retention settings; chat / WhatsApp transcripts like calls."""
    from apps.agents.models import Message
    from apps.audit.models import ApiRequestLog, AuditLog, ErrorLog
    from apps.notifications.models import Notification

    now = now or timezone.now()
    logs = now - timedelta(days=setting("retention.logs_days"))
    out = {
        "api_logs": ApiRequestLog.objects.filter(created_at__lt=logs).delete()[0],
        "error_logs": ErrorLog.objects.filter(created_at__lt=logs).delete()[0],
        "audit": AuditLog.objects.filter(created_at__lt=now - timedelta(days=setting("retention.audit_days"))).delete()[
            0
        ],
    }
    with platform_context():
        out["alerts"] = Notification.all_companies.filter(
            created_at__lt=now - timedelta(days=setting("retention.alerts_days"))
        ).delete()[0]
        companies = list(Company.objects.filter(deleted_at__isnull=True))
    from apps.voice.services import policy

    chats = 0
    for company in companies:
        with company_context(company.id):
            cutoff = now - timedelta(days=policy(company)["transcripts_days"])
            chats += Message.objects.filter(
                company=company, conversation__channel__in=("web_chat", "whatsapp"), conversation__ended_at__lt=cutoff
            ).delete()[0]
    out["chat_transcripts"] = chats
    return out
