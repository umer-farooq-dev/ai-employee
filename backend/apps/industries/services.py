"""Industry templates: versioning, cloning, company upgrade / rollback, and what a company effectively uses.

Platform code: these functions read template rows (no company) and, where a company is given, that company's own
rows. They run inside platform_context() when they touch several companies.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.audit.services import record

from .models import (
    AppointmentType,
    CatalogType,
    FieldDefinition,
    Industry,
    LeadStatus,
    ScoringRule,
    TemplateVersion,
)

CHILD_MODELS = [FieldDefinition, CatalogType, AppointmentType, LeadStatus, ScoringRule]
VERSION_FIELDS = [
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
]
DEFAULT_THRESHOLDS = {"hot": 70, "warm": 40}


# ------------------------------------------------------------------ versioning (IND-03, IND-05)
def _copy_children(source, target):
    for model in CHILD_MODELS:
        for row in model.objects.filter(template_version=source, company__isnull=True):
            row.pk = None
            row.id = None
            row._state.adding = True
            row.template_version = target
            row.save()


@transaction.atomic
def create_draft(industry, from_version=None, user=None, request=None) -> TemplateVersion:
    """New draft = copy of `from_version` (default: the published one). Only one draft at a time."""
    if industry.versions.filter(status=TemplateVersion.DRAFT).exists():
        raise ValidationError("A draft already exists. Edit or publish it first.")
    source = from_version or industry.published_version
    number = (industry.versions.aggregate(m=Max("version"))["m"] or 0) + 1
    draft = TemplateVersion(industry=industry, version=number, status=TemplateVersion.DRAFT)
    if source:
        for f in VERSION_FIELDS:
            setattr(draft, f, getattr(source, f))
        draft.notes = f"Based on v{source.version}"
    draft.save()
    if source:
        _copy_children(source, draft)
    record(
        request, "template.draft", "template_version", draft.id, changes={"industry": industry.key, "version": number}
    )
    return draft


@transaction.atomic
def publish(version, user=None, request=None):
    """Draft (or an archived version, for rollback) becomes the published version; the previous one is archived.
    Companies keep their current version until they accept the update."""
    if version.status == TemplateVersion.PUBLISHED:
        raise ValidationError("This version is already published.")
    industry = Industry.objects.select_for_update().get(pk=version.industry_id)
    rollback = version.status == TemplateVersion.ARCHIVED
    industry.versions.filter(status=TemplateVersion.PUBLISHED).update(status=TemplateVersion.ARCHIVED)
    version.status = TemplateVersion.PUBLISHED
    version.published_at = timezone.now()
    version.published_by = user
    version.save(update_fields=["status", "published_at", "published_by", "updated_at"])
    industry.published_version = version
    industry.save(update_fields=["published_version", "updated_at"])
    record(
        request,
        "template.rollback" if rollback else "template.publish",
        "template_version",
        version.id,
        changes={"industry": industry.key, "version": version.version},
    )
    return version


@transaction.atomic
def clone_industry(source: Industry, key: str, name: str, request=None) -> Industry:
    """IND-05: a new industry (inactive) whose first draft copies the source's published template."""
    if Industry.objects.filter(key=key).exists():
        raise ValidationError("An industry with this key already exists.")
    industry = Industry.objects.create(
        key=key,
        name=name,
        short_description=source.short_description,
        description=source.description,
        icon=source.icon,
        image=source.image,
        supported_languages=source.supported_languages,
        is_active=False,
        sort_order=source.sort_order + 1,
    )
    base = source.published_version or source.versions.order_by("-version").first()
    draft = TemplateVersion.objects.create(industry=industry, version=1, notes=f"Cloned from {source.name}")
    if base:
        for f in VERSION_FIELDS:
            setattr(draft, f, getattr(base, f))
        draft.save()
        _copy_children(base, draft)
    record(request, "industry.clone", "industry", industry.id, changes={"from": source.key})
    return industry


def update_available(company):
    """The industry's published version when the company is on an older one (shown in the company panel)."""
    industry = company.industry
    current = company.template_version
    published = industry.published_version if industry else None
    if published and (not current or published.version > current.version):
        return published
    return None


def assign_version(company, version, request=None):
    """IND-03: company accepts an update (or Super Admin moves it to another version, e.g. rollback)."""
    if version.industry_id != company.industry_id:
        raise ValidationError("That version belongs to another industry.")
    if version.status == TemplateVersion.DRAFT:
        raise ValidationError("Drafts cannot be used by companies.")
    old = company.template_version
    company.template_version = version
    company.save(update_fields=["template_version", "updated_at"])
    record(
        request,
        "company.template_version",
        "company",
        company.id,
        company=company,
        changes={"old": old.version if old else None, "new": version.version},
    )


# ------------------------------------------------------------------ what a company uses
def _scope(company, model):
    """Template rows of the company's version + the company's own rows."""
    version_id = company.template_version_id if company else None
    q = Q(template_version_id=version_id, company__isnull=True) if version_id else Q(pk__in=[])
    if company:
        q |= Q(company=company)
    return model.objects.filter(q)


def fields_for(company, entity="lead"):
    return list(
        _scope(company, FieldDefinition).filter(entity=entity, is_active=True).order_by("sort_order", "created_at")
    )


def catalog_types(company):
    return list(_scope(company, CatalogType).order_by("sort_order", "name"))


def appointment_types(company):
    return list(_scope(company, AppointmentType).filter(is_active=True).order_by("sort_order", "name"))


def statuses(company):
    """The template's statuses, or the platform defaults when the template defines none (CRM-02)."""
    version_id = company.template_version_id if company else None
    rows = list(LeadStatus.objects.filter(template_version_id=version_id, company__isnull=True)) if version_id else []
    if not rows:
        rows = list(LeadStatus.objects.filter(template_version__isnull=True, company__isnull=True))
    return sorted(rows, key=lambda s: (s.sort_order, s.label))


def scoring_rules(company):
    """Template rules; a company rule with the same key replaces the template rule (SCORE-02)."""
    rules = {r.key: r for r in _scope(company, ScoringRule).filter(company__isnull=True)}
    if company:
        rules.update({r.key: r for r in ScoringRule.objects.filter(company=company)})
    return sorted((r for r in rules.values() if r.is_active), key=lambda r: (r.priority, r.name))


def thresholds(company):
    version = company.template_version if company else None
    return {**DEFAULT_THRESHOLDS, **((version.score_thresholds if version else None) or {})}


def status_for_event(company, event):
    version = company.template_version if company else None
    return ((version.status_transitions if version else None) or {}).get(event)
