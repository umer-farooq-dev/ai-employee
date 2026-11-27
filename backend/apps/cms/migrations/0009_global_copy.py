"""Website wording for every country: replaces the India-only texts that are still unchanged (edited texts stay)."""

from django.db import migrations

from apps.cms.global_copy import apply


def forwards(apps, schema_editor):
    Section = apps.get_model("cms", "Section")
    for section in Section.objects.all():
        content, draft = apply(section.content), apply(section.draft_content)
        if content != section.content or draft != section.draft_content:
            section.content, section.draft_content = content, draft
            section.save(update_fields=["content", "draft_content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0008_pricing_subtext_abroad")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
