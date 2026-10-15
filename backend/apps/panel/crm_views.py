"""Company panel CRM (CRM-09 … CRM-17, CP-04, SCORE-02 company adjustments). Logic lives in apps.crm.services."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.services import record
from apps.crm import filters, imports
from apps.crm import services as crm
from apps.crm.models import AssignmentRule, LeadImport, SavedView, Task
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.industries.models import FieldDefinition, LeadSource, ScoringRule
from apps.rbac.services import has_perm

from .company_views import _errors, company_perm
from .crm_forms import AssignmentRuleForm, CompanyFieldForm, CompanyScoringRuleForm, FollowUpForm, LeadForm, TaskForm

PER_PAGE = 25


def _can(request, key):
    return has_perm(request.user, key, request.company)


def _lead(request, pk, include_deleted=False):
    return get_object_or_404(crm.visible(request, include_deleted=include_deleted), pk=pk)


# ------------------------------------------------------------------ list, saved views, bulk (CRM-09, CRM-17)
@company_perm("leads.view")
def lead_list(request):
    company = request.company
    if request.method == "POST":
        return _list_post(request)
    qs, custom_filters = filters.apply(request, request.GET)
    page = Paginator(qs, PER_PAGE).get_page(request.GET.get("page"))
    list_fields = [d for d in templates.fields_for(company, "lead") if d.show_in_list]
    rows = [(lead, [field_engine.display(d, lead.custom.get(d.key)) for d in list_fields]) for lead in page]
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "panel/company/crm/leads.html",
        {
            "page": page,
            "rows": rows,
            "list_fields": list_fields,
            "custom_filters": custom_filters,
            "statuses": templates.statuses(company),
            "sources": LeadSource.objects.filter(is_active=True),
            "members": crm.members(company),
            "saved_views": SavedView.objects.filter(user=request.user),
            "params": params.urlencode(),
            "p": request.GET,
            "now": timezone.now(),
            "can": {k: _can(request, f"leads.{k}") for k in ("manage", "assign", "delete", "import", "export")},
        },
    )


def _list_post(request):
    op = request.POST.get("op")
    back = request.POST.get("back") or reverse("panel:lead_list")
    try:
        if op == "save_view":
            name = (request.POST.get("name") or "").strip()[:80]
            if not name:
                raise ValidationError("Give the view a name.")
            SavedView.objects.update_or_create(
                company=request.company,
                user=request.user,
                name=name,
                defaults={"params": request.POST.get("params", "")[:2000]},
            )
            messages.success(request, f"View “{name}” saved.")
        elif op == "delete_view":
            SavedView.objects.filter(user=request.user, pk=request.POST.get("view")).delete()
        elif op == "bulk":
            action = request.POST.get("action")
            need = {
                "assign": "leads.assign",
                "status": "leads.assign",
                "tag": "leads.manage",
                "delete": "leads.delete",
                "add_to_campaign": "leads.assign",
                "export": "leads.export",
            }.get(action)
            if not need or not _can(request, need):
                raise PermissionDenied
            leads = crm.visible(request).filter(pk__in=request.POST.getlist("ids"))
            if not leads.exists():
                raise ValidationError("Select at least one lead.")
            if action == "export":
                return _export_response(request, leads, request.POST.get("format", "csv"))
            count = crm.bulk(request.company, leads, action, request.POST.get("value"), request.user, request=request)
            messages.success(request, f"{count} lead(s) updated.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect(back if back.startswith("/") and not back.startswith("//") else reverse("panel:lead_list"))


def _export_response(request, leads, fmt):
    data, content_type, ext = crm.export(
        request.company, leads, "xlsx" if fmt == "xlsx" else "csv", request.user, request=request
    )
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="leads-{timezone.localdate():%Y%m%d}.{ext}"'
    return response


@company_perm("leads.export")
def lead_export(request):
    qs, _ = filters.apply(request, request.GET)
    try:
        return _export_response(request, qs, request.GET.get("format", "csv"))
    except ValidationError as exc:
        _errors(request, exc)
        return redirect(f"{reverse('panel:lead_list')}?{request.GET.urlencode()}")


# ------------------------------------------------------------------ pipeline (CRM-10)
@company_perm("leads.view")
def lead_board(request):
    qs, _ = filters.apply(request, request.GET)
    statuses = templates.statuses(request.company)
    columns = {s.pk: {"status": s, "leads": []} for s in statuses}
    for lead in qs[:1000]:
        if lead.status_id in columns:
            columns[lead.status_id]["leads"].append(lead)
    return render(
        request,
        "panel/company/crm/board.html",
        {
            "columns": columns.values(),
            "can_move": _can(request, "leads.manage"),
            "p": request.GET,
        },
    )


# ------------------------------------------------------------------ create / edit / detail (CRM-11, CRM-12)
@company_perm("leads.manage")
def lead_form(request, pk=None):
    company = request.company
    lead = _lead(request, pk) if pk else None
    form = LeadForm(request.POST or None, company=company, lead=lead, can_assign=_can(request, "leads.assign"))
    duplicate = None
    if request.method == "POST" and form.is_valid():
        try:
            data = form.lead_data()
            if lead:
                crm.update_lead(lead, data, request.user, request=request)
            else:
                if not _can(request, "leads.view_all") and not data.get("assigned_user"):
                    data["assigned_user"] = request.user  # agents see only their own leads
                lead = crm.create_lead(company, data, request.user, request=request)
            messages.success(request, f"Lead {lead.reference} saved.")
            return redirect("panel:lead_detail", pk=lead.pk)
        except crm.DuplicateLead as exc:
            duplicate = exc.lead
            form.add_error(None, exc.messages[0])
        except ValidationError as exc:
            for m in exc.messages:
                form.add_error(None, m)
    return render(request, "panel/company/crm/lead_form.html", {"form": form, "lead": lead, "duplicate": duplicate})


@company_perm("leads.view")
def lead_detail(request, pk):
    lead = _lead(request, pk, include_deleted=_can(request, "leads.delete"))
    if request.method == "POST":
        return _detail_post(request, lead)
    defs = templates.fields_for(request.company, "lead")
    return render(
        request,
        "panel/company/crm/lead_detail.html",
        {
            "lead": lead,
            "custom": [(d, field_engine.display(d, lead.custom.get(d.key))) for d in defs],
            "activities": lead.activities.select_related("actor")[:200],
            "notes": lead.notes.select_related("author"),
            "tasks": lead.tasks.select_related("assigned_user").order_by("status", "due_at"),
            "score_events": lead.score_events.all()[:10],
            "statuses": templates.statuses(request.company),
            "members": crm.members(request.company),
            "task_form": TaskForm(company=request.company),
            "follow_form": FollowUpForm(),
            "now": timezone.now(),
            "can": {k: _can(request, f"leads.{k}") for k in ("manage", "assign", "delete")},
        },
    )


def _detail_post(request, lead):
    op = request.POST.get("op")
    need = {"assign": "leads.assign", "delete": "leads.delete", "restore": "leads.delete"}.get(op, "leads.manage")
    if not _can(request, need):
        raise PermissionDenied
    try:
        if op == "note":
            crm.add_note(lead, request.POST.get("body"), request.user, request=request)
        elif op == "status":
            crm.set_status(lead, request.POST.get("status"), request.user, request=request)
        elif op == "assign":
            crm.assign(lead, request.POST.get("user") or None, request.user, request=request)
        elif op == "follow_up":
            form = FollowUpForm(request.POST)
            if not form.is_valid():
                raise ValidationError("Choose the follow-up date and time.")
            crm.schedule_follow_up(
                lead, form.cleaned_data["when"], form.cleaned_data["next_action"], request.user, request=request
            )
        elif op == "task":
            form = TaskForm(request.POST, company=request.company)
            if not form.is_valid():
                raise ValidationError([e for errs in form.errors.values() for e in errs])
            crm.create_task(request.company, {**form.cleaned_data, "lead": lead}, request.user, request=request)
        elif op == "task_done":
            crm.complete_task(get_object_or_404(Task, pk=request.POST.get("task"), lead=lead), request.user)
        elif op == "delete":
            crm.soft_delete(lead, request.user, request=request)
            messages.success(request, "Lead deleted. You can restore it from the deleted leads list.")
            return redirect("panel:lead_list")
        elif op == "restore":
            crm.restore(lead, request.user, request=request)
        messages.success(request, "Saved.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("panel:lead_detail", pk=lead.pk)


# ------------------------------------------------------------------ import (CRM-13)
@company_perm("leads.import")
def lead_import(request, pk=None):
    company = request.company
    imp = get_object_or_404(LeadImport, pk=pk) if pk else None
    if request.method == "POST":
        try:
            if not imp:
                upload = request.FILES.get("file")
                if not upload:
                    raise ValidationError("Choose a CSV or Excel file.")
                imp = imports.start(company, upload, request.user, request=request)
                return redirect("panel:lead_import_map", pk=imp.pk)
            if imp.status != LeadImport.PENDING:
                raise ValidationError("This import has already run.")
            mapping = {h: request.POST.get(f"map_{i}", "") for i, h in enumerate(imp.headers)}
            imports.run(imp, mapping, request.POST.get("duplicate_mode", "skip"), request.user, request=request)
            return redirect("panel:lead_import_map", pk=imp.pk)
        except ValidationError as exc:
            _errors(request, exc)
            return redirect(request.path)
    if imp and request.GET.get("report"):
        response = HttpResponse(imports.error_report(imp), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="import-errors-{imp.pk}.csv"'
        return response
    return render(
        request,
        "panel/company/crm/import.html",
        {
            "imp": imp,
            "targets": imports.targets(company),
            "columns": list(enumerate(imp.headers)) if imp else [],
            "recent": LeadImport.objects.all()[:10],
        },
    )


# ------------------------------------------------------------------ duplicates (CRM-14)
@company_perm("leads.delete")
def duplicates(request):
    if request.method == "POST":
        primary = _lead(request, request.POST.get("primary"))
        others = list(crm.visible(request).filter(pk__in=request.POST.getlist("merge")))
        try:
            crm.merge(primary, others, request.user, request=request)
            messages.success(request, f"Merged into {primary.reference}.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:lead_duplicates")
    return render(request, "panel/company/crm/duplicates.html", {"groups": crm.duplicate_groups(request.company)})


# ------------------------------------------------------------------ tasks (CRM-16)
@company_perm("leads.view")
def tasks(request):
    if request.method == "POST":
        task = get_object_or_404(Task, pk=request.POST.get("task"))
        if task.assigned_user_id != request.user.id and not _can(request, "leads.view_all"):
            raise PermissionDenied
        crm.complete_task(task, request.user)
        messages.success(request, "Task done.")
        return redirect(request.get_full_path())
    mine = request.GET.get("all") != "1" or not _can(request, "leads.view_all")
    qs = Task.objects.filter(status=Task.OPEN).select_related("lead", "assigned_user")
    if mine:
        qs = qs.filter(assigned_user=request.user)
    today = timezone.localdate()
    return render(
        request,
        "panel/company/crm/tasks.html",
        {
            "today": [t for t in qs if timezone.localtime(t.due_at).date() <= today],
            "upcoming": [t for t in qs if timezone.localtime(t.due_at).date() > today][:100],
            "mine": mine,
            "can_all": _can(request, "leads.view_all"),
        },
    )


# ------------------------------------------------------------------ global search (CP-04)
@company_perm("leads.view")
def search(request):
    q = request.GET.get("q", "")
    return render(request, "panel/company/crm/search.html", {"q": q, "results": crm.search(request, q, limit=50)})


# ------------------------------------------------------------------ company CRM settings (CRM-04, CRM-15, SCORE-02)
@company_perm("crm.configure")
def crm_settings(request):
    company = request.company
    template_rules = (
        list(ScoringRule.objects.filter(template_version=company.template_version_id, company__isnull=True))
        if company.template_version_id
        else []
    )
    return render(
        request,
        "panel/company/crm/settings.html",
        {
            "template_fields": (
                FieldDefinition.objects.filter(
                    template_version=company.template_version_id, company__isnull=True, entity="lead"
                )
                if company.template_version_id
                else []
            ),
            "company_fields": FieldDefinition.objects.filter(company=company, entity="lead"),
            "field_limit": crm.custom_field_limit(company),
            "rules": templates.scoring_rules(company),
            "template_rules": template_rules,
            "company_rules": ScoringRule.objects.filter(company=company),
            "assignment_rules": AssignmentRule.objects.all(),
        },
    )


def _company_item(request, model, form_class, pk, label, extra=None, before_save=None):
    item = get_object_or_404(model, pk=pk, company=request.company) if pk else None
    back = reverse("panel:crm_settings")
    if request.method == "POST" and request.POST.get("op") == "delete" and item:
        item.delete()
        record(request, f"crm.{model.__name__.lower()}_delete", model.__name__.lower(), pk, company=request.company)
        messages.success(request, f"{label} deleted.")
        return redirect(back)
    form = form_class(request.POST or None, instance=item, **(extra or {}))
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.company = request.company
        try:
            if before_save:
                before_save(obj)
            obj.save()
            record(
                request, f"crm.{model.__name__.lower()}_save", model.__name__.lower(), obj.id, company=request.company
            )
            messages.success(request, f"{label} saved.")
            return redirect(back)
        except ValidationError as exc:
            for m in exc.messages:
                form.add_error(None, m)
    return render(
        request, "panel/company/form.html", {"form": form, "title": label, "back_url": back, "delete": bool(item)}
    )


@company_perm("crm.configure")
def company_field(request, pk=None):
    company = request.company

    def check(obj):
        limit = crm.custom_field_limit(company)
        count = FieldDefinition.objects.filter(company=company, entity="lead").exclude(pk=obj.pk).count()
        if obj._state.adding and limit is not None and count >= limit:
            raise ValidationError(f"Your plan allows {limit} custom fields. Upgrade to add more.")
        template_keys = {d.key for d in templates.fields_for(company, "lead") if d.company_id is None}
        own = FieldDefinition.objects.filter(company=company, entity="lead", key=obj.key).exclude(pk=obj.pk)
        if obj.key in template_keys or own.exists():
            raise ValidationError("This key is already used by another lead field.")
        obj.entity = "lead"

    return _company_item(request, FieldDefinition, CompanyFieldForm, pk, "Custom lead field", before_save=check)


@company_perm("crm.configure")
def company_scoring_rule(request, pk=None):
    """Adjust a template rule (?from=<rule id> copies it under the same key) or add a company rule."""
    initial_from = request.GET.get("from")
    if not pk and initial_from and request.method == "GET":
        src = get_object_or_404(ScoringRule, pk=initial_from, company__isnull=True)
        existing = ScoringRule.objects.filter(company=request.company, key=src.key).first()
        if existing:
            return redirect("panel:crm_scoring_rule_edit", pk=existing.pk)
        copy = ScoringRule.objects.create(
            company=request.company,
            key=src.key,
            name=src.name,
            condition=src.condition,
            points=src.points,
            force_label=src.force_label,
            priority=src.priority,
            is_active=src.is_active,
        )
        return redirect("panel:crm_scoring_rule_edit", pk=copy.pk)
    return _company_item(request, ScoringRule, CompanyScoringRuleForm, pk, "Scoring rule")


@company_perm("crm.configure")
def assignment_rule(request, pk=None):
    return _company_item(
        request, AssignmentRule, AssignmentRuleForm, pk, "Assignment rule", extra={"company": request.company}
    )


@require_POST
@company_perm("leads.manage")
def lead_status(request, pk):
    """CRM-10 pipeline drag-and-drop (fetch → 204 / 400) and plain form posts (→ back to the board)."""
    lead = _lead(request, pk)
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    try:
        crm.set_status(lead, request.POST.get("status"), request.user, request=request)
    except ValidationError as exc:
        if is_fetch:
            return HttpResponse(" ".join(exc.messages), status=400)
        _errors(request, exc)
    return HttpResponse(status=204) if is_fetch else redirect("panel:lead_board")
