from django.db import migrations

from apps.cms.seed_content import INDUSTRIES


def seed(apps, schema_editor):
    Industry = apps.get_model("industries", "Industry")
    for order, (key, name, short, description, icon) in enumerate(INDUSTRIES):
        Industry.objects.get_or_create(key=key, defaults={"name": name, "short_description": short,
                                                          "description": description, "icon": icon,
                                                          "is_active": True, "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("industries", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
