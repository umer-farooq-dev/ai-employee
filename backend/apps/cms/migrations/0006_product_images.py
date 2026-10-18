"""Website sections showed the purchased template's sample screenshots (HR dashboards, a stock photo). Swap them for
screenshots of the product itself wherever a section still has the sample image; images set in Super Admin stay."""

import copy

from django.db import migrations

from apps.cms.seed_content import apply_product_images


def swap(apps, schema_editor):
    Section = apps.get_model("cms", "Section")
    for s in Section.objects.select_related("page", "section_type"):
        key = (s.page.key, s.section_type.key)
        content = apply_product_images(*key, copy.deepcopy(s.content or {}))
        draft = apply_product_images(*key, copy.deepcopy(s.draft_content)) if s.draft_content else s.draft_content
        if content != s.content or draft != s.draft_content:
            s.content, s.draft_content = content, draft
            s.save(update_fields=["content", "draft_content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0005_brand_badge")]
    operations = [migrations.RunPython(swap, migrations.RunPython.noop)]
