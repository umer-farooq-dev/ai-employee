"""The 404 page as an editable CMS page (Website → Page not found), seeded like the other inner pages."""

import importlib

from django.db import migrations


def seed(apps, schema_editor):
    importlib.import_module("apps.cms.migrations.0003_phase2_pages_and_content").seed(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("cms", "0003_phase2_pages_and_content")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
