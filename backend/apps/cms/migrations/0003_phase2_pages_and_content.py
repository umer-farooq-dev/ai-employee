from django.db import migrations

from apps.cms.schemas import SECTION_TYPES, SEED_PAGES
from apps.cms.seed_content import CONTENT, HIDDEN


def seed(apps, schema_editor):
    """New section types and inner pages (WEB-02), then seed content written into sections that were never edited."""
    SectionType = apps.get_model("cms", "SectionType")
    Page = apps.get_model("cms", "Page")
    Section = apps.get_model("cms", "Section")
    SectionVersion = apps.get_model("cms", "SectionVersion")

    types = {}
    for key, name, description, dynamic, schema in SECTION_TYPES:
        types[key], _ = SectionType.objects.update_or_create(
            key=key, defaults={"name": name, "description": description, "is_dynamic": dynamic, "schema": schema})
    for order, (key, slug, title, section_keys) in enumerate(SEED_PAGES):
        page, created = Page.objects.get_or_create(key=key, defaults={"slug": slug, "title": title, "is_system": True,
                                                                       "sort_order": order})
        if created:
            for position, type_key in enumerate(section_keys):
                Section.objects.create(page=page, section_type=types[type_key], sort_order=position,
                                       anchor_id=type_key if key == "home" else "")

    for section in Section.objects.select_related("page", "section_type"):
        content = CONTENT.get((section.page.key, section.section_type.key))
        if content is None or section.version or section.content or section.draft_content:
            continue  # already edited in Super Admin
        section.content = content
        section.version = 1
        section.is_visible = (section.page.key, section.section_type.key) not in HIDDEN
        section.save()
        SectionVersion.objects.create(section=section, version=1, content=content)


class Migration(migrations.Migration):
    dependencies = [("cms", "0002_seed_cms")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
