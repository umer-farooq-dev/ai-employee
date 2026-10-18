"""Super Admin: industry templates (SA-05, IND-01 … IND-05), CRM configuration (SA-07), roles (ROLE-01), holidays."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.audit.services import record
from apps.industries import editor
from apps.industries import services as templates
from apps.industries.models import (
    AppointmentType,
    CatalogType,
    FieldDefinition,
    Holiday,
    Industry,
    LeadSource,
    LeadStatus,
    ScoringRule,
    TemplateVersion,
)
from apps.roles_tools.models import EmployeeRole, Tool
from apps.tenancy.models import Company

from . import cms_form
from .template_forms import (
    AppointmentTypeForm,
    CatalogTypeForm,
    EmployeeRoleForm,
    FieldDefinitionForm,
    HolidayForm,
    IndustryCloneForm,
    LeadSourceForm,
    LeadStatusForm,
    ScoringRuleForm,
    ToolForm,
)
from .views import _errors, staff_perm

# kind in URL → (model, form, label, tab)
KINDS = {
    "fields": (FieldDefinition, FieldDefinitionForm, "Field", "fields"),
    "catalog-types": (CatalogType, CatalogTypeForm, "Catalogue type", "catalogue"),
    "appointment-types": (AppointmentType, AppointmentTypeForm, "Appointment type", "appointments"),
    "statuses": (LeadStatus, LeadStatusForm, "Lead status", "statuses"),
    "scoring": (ScoringRule, ScoringRuleForm, "Scoring rule", "scoring"),
}
TABS = [
    ("general", "General"),
    ("fields", "Lead fields"),
    ("catalogue", "Catalogue"),
    ("appointments", "Appointment types"),
    ("statuses", "Lead statuses"),
    ("scoring", "Scoring rules"),
]


# ------------------------------------------------------------------ industry versions (IND-03, IND-05)
@staff_perm("industries.manage")
def industry_templates(request, pk):
    industry = get_object_or_404(Industry, pk=pk)
    if request.method == "POST":
        op = request.POST.get("op")
        try:
            if op == "draft":
                source = industry.versions.filter(pk=request.POST.get("from")).first()
                draft = templates.create_draft(industry, source, request.user, request=request)
                messages.success(request, f"Draft v{draft.version} created.")
                return redirect("superadmin:template_version", pk=draft.pk)
            if op == "publish":
                version = get_object_or_404(TemplateVersion, pk=request.POST.get("version"), industry=industry)
                templates.publish(version, request.user, request=request)
                messages.success(request, f"v{version.version} is now published. Companies upgrade when they accept.")
            if op == "clone":
                form = IndustryCloneForm(request.POST)
                if not form.is_valid():
                    raise ValidationError([e for errs in form.errors.values() for e in errs])
                clone = templates.clone_industry(
                    industry, form.cleaned_data["key"], form.cleaned_data["name"], request=request
                )
                messages.success(request, f"{clone.name} created as an inactive industry with a draft template.")
                return redirect("superadmin:industry_templates", pk=clone.pk)
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("superadmin:industry_templates", pk=pk)
    versions = industry.versions.annotate(company_count=Count("companies")).order_by(*TemplateVersion._meta.ordering)
    return render(
        request,
        "panel/admin/industries/templates.html",
        {"industry": industry, "versions": versions, "clone_form": IndustryCloneForm()},
    )


def _entities(version):
    return [("lead", "Lead (CRM)")] + [
        (t.entity, f"Catalogue: {t.name}") for t in CatalogType.objects.filter(template_version=version)
    ]


def _statuses(version):
    return list(LeadStatus.objects.filter(template_version=version)) or list(
        LeadStatus.objects.filter(template_version__isnull=True, company__isnull=True)
    )


@staff_perm("industries.manage")
def template_version(request, pk):
    version = get_object_or_404(TemplateVersion.objects.select_related("industry"), pk=pk)
    tab = request.GET.get("tab", "general")
    lead_fields = FieldDefinition.objects.filter(template_version=version, entity="lead")
    statuses = _statuses(version)
    the_schema = editor.schema(lead_fields, statuses)
    if request.method == "POST":
        if not version.editable:
            messages.error(request, "Published and archived versions cannot be changed. Create a draft.")
            return redirect("superadmin:template_version", pk=pk)
        try:
            editor.apply_content(version, the_schema, cms_form.parse(the_schema, request.POST, request.FILES), statuses)
            version.notes = request.POST.get("notes", version.notes)
            version.save()
            record(request, "template.update", "template_version", version.id)
            messages.success(request, "Template saved.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect(f"{reverse('superadmin:template_version', args=[pk])}?tab=general")
    rows = {
        "fields": FieldDefinition.objects.filter(template_version=version).order_by("entity", "sort_order"),
        "catalogue": CatalogType.objects.filter(template_version=version),
        "appointments": AppointmentType.objects.filter(template_version=version),
        "statuses": LeadStatus.objects.filter(template_version=version),
        "scoring": ScoringRule.objects.filter(template_version=version).order_by("priority"),
    }
    return render(
        request,
        "panel/admin/industries/version.html",
        {
            "version": version,
            "tab": tab,
            "tabs": TABS,
            "rows": rows,
            "fields": cms_form.editor_fields(the_schema, editor.to_content(version)),
            "uses_platform_statuses": not rows["statuses"].exists(),
        },
    )


@staff_perm("industries.manage")
def template_child(request, vid, kind, pk=None):
    version = get_object_or_404(TemplateVersion, pk=vid)
    model, form_class, label, tab = KINDS[kind]
    item = get_object_or_404(model, pk=pk, template_version=version) if pk else None
    back = f"{reverse('superadmin:template_version', args=[vid])}?tab={tab}"
    if request.method == "POST" and not version.editable:
        messages.error(request, "Only drafts can be changed.")
        return redirect(back)
    if request.method == "POST" and request.POST.get("op") == "delete" and item:
        item.delete()
        record(request, "template.child_delete", kind, pk)
        messages.success(request, f"{label} deleted.")
        return redirect(back)
    extra = {"entities": _entities(version)} if model is FieldDefinition else {}
    form = form_class(request.POST or None, instance=item, **extra)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.template_version = version
        lookup = {"template_version": version, "key": obj.key}
        if model is FieldDefinition:
            lookup["entity"] = obj.entity
        if model.objects.filter(**lookup).exclude(pk=obj.pk).exists():
            form.add_error("key", "This key is already used in this version.")
        else:
            obj.save()
            if hasattr(form, "save_m2m"):
                form.save_m2m()
            record(request, "template.child_save", kind, obj.id)
            messages.success(request, f"{label} saved.")
            return redirect(back)
    return render(
        request,
        "panel/admin/form.html",
        {
            "form": form,
            "title": f"{version} · {label}",
            "back_url": back,
            "readonly": not version.editable,
            "delete": bool(item and version.editable),
        },
    )


# ------------------------------------------------------------------ companies on versions (IND-03)
@require_POST
@staff_perm("companies.manage")
def company_template(request, pk):
    company = get_object_or_404(Company, pk=pk)
    version = get_object_or_404(TemplateVersion, pk=request.POST.get("version"))
    try:
        templates.assign_version(company, version, request=request)
        messages.success(request, f"{company.name} now uses {version}.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("superadmin:company_detail", pk=pk)


# ------------------------------------------------------------------ CRM configuration (SA-07), holidays, roles
PLATFORM_KINDS = {
    # kind: (model, form, label, permission, queryset filter, list template title)
    "statuses": (
        LeadStatus,
        LeadStatusForm,
        "Default lead status",
        "crm_config.manage",
        {"template_version__isnull": True, "company__isnull": True},
    ),
    "sources": (LeadSource, LeadSourceForm, "Lead source", "crm_config.manage", {}),
    "holidays": (Holiday, HolidayForm, "Holiday", "holidays.manage", {}),
    "employee-roles": (EmployeeRole, EmployeeRoleForm, "AI Employee role", "employee_roles.manage", {}),
    "tools": (Tool, ToolForm, "Tool", "tools.manage", {}),
}


def _platform_list_view(kind):
    model, _, label, perm, filters = PLATFORM_KINDS[kind]

    @staff_perm(perm)
    def view(request):
        return render(
            request,
            "panel/admin/platform_list.html",
            {
                "kind": kind,
                "label": label,
                "items": model.objects.filter(**filters),
            },
        )

    return view


crm_statuses = _platform_list_view("statuses")
crm_sources = _platform_list_view("sources")
holidays = _platform_list_view("holidays")
employee_roles = _platform_list_view("employee-roles")
tools = _platform_list_view("tools")


def platform_item(request, kind, pk=None):
    model, form_class, label, perm, filters = PLATFORM_KINDS[kind]

    @staff_perm(perm)
    def view(request):
        item = get_object_or_404(model, pk=pk, **filters) if pk else None
        back = reverse(f"superadmin:{kind.replace('-', '_')}")
        if request.method == "POST" and request.POST.get("op") == "delete" and item:
            if getattr(item, "is_system", False):
                messages.error(request, "Seeded statuses cannot be deleted; rename or reorder them instead.")
                return redirect(back)
            item.delete()
            record(request, f"{kind}.delete", kind, pk)
            messages.success(request, f"{label} deleted.")
            return redirect(back)
        form = form_class(request.POST or None, request.FILES or None, instance=item)
        if request.method == "POST" and form.is_valid():
            obj = form.save()
            record(request, f"{kind}.save", kind, obj.id)
            messages.success(request, f"{label} saved.")
            return redirect(back)
        return render(
            request,
            "panel/admin/form.html",
            {
                "form": form,
                "title": label,
                "back_url": back,
                "delete": bool(item),
            },
        )

    return view(request)
