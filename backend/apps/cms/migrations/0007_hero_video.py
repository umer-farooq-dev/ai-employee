"""Hero section: an optional main video (Super Admin upload) that plays muted on a loop in place of the main image."""

from django.db import migrations

FIELD = {
    "key": "main_video",
    "label": "Main video (plays muted on a loop; the main image shows until it loads)",
    "type": "video",
}


def add(apps, schema_editor):
    SectionType = apps.get_model("cms", "SectionType")
    hero = SectionType.objects.filter(key="hero").first()
    if not hero or any(f["key"] == FIELD["key"] for f in hero.schema):
        return
    keys = [f["key"] for f in hero.schema]
    at = keys.index("main_image") + 1 if "main_image" in keys else len(keys)
    hero.schema = [*hero.schema[:at], FIELD, *hero.schema[at:]]
    hero.save(update_fields=["schema"])


def remove(apps, schema_editor):
    SectionType = apps.get_model("cms", "SectionType")
    hero = SectionType.objects.filter(key="hero").first()
    if hero:
        hero.schema = [f for f in hero.schema if f["key"] != FIELD["key"]]
        hero.save(update_fields=["schema"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0006_product_images")]
    operations = [migrations.RunPython(add, remove)]
