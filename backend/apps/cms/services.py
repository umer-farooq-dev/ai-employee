"""Website content: validate against the section schema, keep drafts, publish with versions (WEB-04)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record

from .models import Page, Section, SectionVersion

SCALAR_TYPES = {"text", "textarea", "rich", "image", "number"}


def _clean_value(field, value):
    t = field["type"]
    if t == "link":
        value = value if isinstance(value, dict) else {}
        return {"label": str(value.get("label", "")).strip(), "url": str(value.get("url", "")).strip()}
    if t == "list":
        rows = value if isinstance(value, list) else []
        rows = [{sub["key"]: _clean_value(sub, (row or {}).get(sub["key"])) for sub in field["fields"]} for row in rows]
        rows = [r for r in rows if any(v not in ("", None, {}) for v in r.values())]
        if field.get("max") and len(rows) > field["max"]:
            raise ValidationError(f"{field['label']}: at most {field['max']} items.")
        return rows
    if t == "number":
        if value in ("", None):
            return None
        try:
            return float(value) if "." in str(value) else int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{field['label']}: enter a number.") from None
    return "" if value is None else str(value).strip()


def clean_content(schema, data):
    """Keep only schema keys, normalise every value. Unknown keys are dropped."""
    data = data or {}
    return {field["key"]: _clean_value(field, data.get(field["key"])) for field in schema}


def save_draft(section: Section, data, user=None, request=None):
    section.draft_content = clean_content(section.section_type.schema, data)
    section.updated_by = user
    section.save(update_fields=["draft_content", "updated_by", "updated_at"])
    record(request, "cms.save_draft", "cms_section", section.id)
    return section


@transaction.atomic
def publish(section: Section, user=None, request=None):
    if section.draft_content is not None:
        section.content = section.draft_content
    section.draft_content = None
    section.version += 1
    section.published_at = timezone.now()
    section.updated_by = user
    section.save()
    SectionVersion.objects.create(section=section, version=section.version, content=section.content, published_by=user)
    record(request, "cms.publish", "cms_section", section.id, changes={"version": section.version})
    return section


def restore(section: Section, version: int, user=None, request=None):
    """Put an older published version back as a draft (publish it to make it live)."""
    old = section.versions.get(version=version)
    section.draft_content = old.content
    section.save(update_fields=["draft_content", "updated_at"])
    record(request, "cms.restore_version", "cms_section", section.id, changes={"version": version})
    return section


def set_visibility(section: Section, visible: bool, request=None):
    section.is_visible = visible
    section.save(update_fields=["is_visible", "updated_at"])
    record(request, "cms.visibility", "cms_section", section.id, changes={"visible": visible})


@transaction.atomic
def reorder(page: Page, section_ids, request=None):
    sections = {str(s.id): s for s in page.sections.all()}
    if set(map(str, section_ids)) != set(sections):
        raise ValidationError("The order must list every section of the page exactly once.")
    for position, sid in enumerate(section_ids):
        Section.objects.filter(id=sid).update(sort_order=position)
    record(request, "cms.reorder", "cms_page", page.id)


def update_seo(page: Page, data, request=None):
    page.seo = {k: str(data.get(k, "")).strip() for k in ("meta_title", "meta_description", "og_image")}
    page.save(update_fields=["seo", "updated_at"])
    record(request, "cms.seo", "cms_page", page.id)


def published_page(slug: str):
    """What the website (and the future app) sees: only visible sections, only published content."""
    page = Page.objects.get(slug=slug)
    sections = page.sections.filter(is_visible=True).select_related("section_type")
    return page, [
        {"type": s.section_type.key, "anchor": s.anchor_id, "content": s.content, "version": s.version}
        for s in sections
    ]
