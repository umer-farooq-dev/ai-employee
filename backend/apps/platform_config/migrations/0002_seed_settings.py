from django.db import migrations

from apps.platform_config.registry import SETTINGS


def seed(apps, schema_editor):
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for s in SETTINGS:
        PlatformSetting.objects.get_or_create(key=s.key, defaults={"value": s.default})


class Migration(migrations.Migration):
    dependencies = [("platform_config", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
