"""Plans are bought, not tried: pricing texts that still offer the free trial (in their original wording) change."""

from django.db import migrations

NO_TRIAL = {
    "Start with a free trial. Prices exclude GST.": "Prices exclude GST.",
    "Start with a free trial.": "",
    "Start free trial": "Get started",
    "Simple plans. Start with a free trial.": "Simple plans. Pay monthly or yearly, cancel any time.",
}


def swap(value):
    if isinstance(value, dict):
        return {k: swap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [swap(v) for v in value]
    return NO_TRIAL.get(value, value) if isinstance(value, str) else value


def forwards(apps, schema_editor):
    Section = apps.get_model("cms", "Section")
    for section in Section.objects.all():
        content, draft = swap(section.content), swap(section.draft_content)
        if content != section.content or draft != section.draft_content:
            section.content, section.draft_content = content, draft
            section.save(update_fields=["content", "draft_content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0009_global_copy")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
