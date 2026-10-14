from django.db import migrations

from apps.cms.schemas import SECTION_TYPES, SEED_PAGES


def seed(apps, schema_editor):
    SectionType = apps.get_model("cms", "SectionType")
    Page = apps.get_model("cms", "Page")
    Section = apps.get_model("cms", "Section")
    types = {}
    for key, name, description, dynamic, schema in SECTION_TYPES:
        types[key], _ = SectionType.objects.get_or_create(
            key=key, defaults={"name": name, "description": description, "is_dynamic": dynamic, "schema": schema})
    for order, (key, slug, title, section_keys) in enumerate(SEED_PAGES):
        page, created = Page.objects.get_or_create(key=key, defaults={"slug": slug, "title": title, "is_system": True,
                                                                       "sort_order": order})
        if created:
            for position, type_key in enumerate(section_keys):
                Section.objects.create(page=page, section_type=types[type_key], sort_order=position,
                                       anchor_id=type_key if key == "home" else "")


class Migration(migrations.Migration):
    dependencies = [("cms", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
