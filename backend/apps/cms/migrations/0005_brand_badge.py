"""Section badges showed the purchased template's own logo (eSoft "S"). Swap that seeded image for the platform's badge
wherever a section still uses it; images changed in Super Admin are left alone."""

from django.db import migrations

SWAP = {"/static/website/img/logo/span9.svg": "/static/brand/badge.svg"}


def _swap(value):
    if isinstance(value, dict):
        return {k: _swap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap(v) for v in value]
    return SWAP.get(value, value) if isinstance(value, str) else value


def swap(apps, schema_editor):
    Section = apps.get_model("cms", "Section")
    for s in Section.objects.all():
        content, draft = _swap(s.content), _swap(s.draft_content)
        if content != s.content or draft != s.draft_content:
            s.content, s.draft_content = content, draft
            s.save(update_fields=["content", "draft_content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0004_not_found_page")]
    operations = [migrations.RunPython(swap, migrations.RunPython.noop)]
