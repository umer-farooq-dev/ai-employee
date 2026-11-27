"""Pricing section: a sub-text for visitors outside the seller's country (prices in their currency, no GST)."""

from django.db import migrations

FIELD = {
    "key": "subtext_abroad",
    "label": "Sub-text for visitors abroad (shown instead; empty = no sub-text)",
    "type": "textarea",
}
GST_LINE = "Prices exclude GST."


def add(apps, schema_editor):
    SectionType = apps.get_model("cms", "SectionType")
    Section = apps.get_model("cms", "Section")
    pricing = SectionType.objects.filter(key="pricing").first()
    if not pricing or any(f["key"] == FIELD["key"] for f in pricing.schema):
        return
    keys = [f["key"] for f in pricing.schema]
    at = keys.index("subtext") + 1 if "subtext" in keys else len(keys)
    pricing.schema = [*pricing.schema[:at], FIELD, *pricing.schema[at:]]
    pricing.save(update_fields=["schema"])
    for section in Section.objects.filter(section_type=pricing):
        for name in ("content", "draft_content"):
            data = getattr(section, name)
            if isinstance(data, dict) and FIELD["key"] not in data:
                data[FIELD["key"]] = " ".join(str(data.get("subtext", "")).replace(GST_LINE, "").split())
        section.save(update_fields=["content", "draft_content"])


def remove(apps, schema_editor):
    SectionType = apps.get_model("cms", "SectionType")
    pricing = SectionType.objects.filter(key="pricing").first()
    if pricing:
        pricing.schema = [f for f in pricing.schema if f["key"] != FIELD["key"]]
        pricing.save(update_fields=["schema"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0007_hero_video")]
    operations = [migrations.RunPython(add, remove)]
