"""New companies buy a plan after approval instead of a free trial (Registration → free trial off)."""

from django.core.cache import cache
from django.db import migrations


def forwards(apps, schema_editor):
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    PlatformSetting.objects.filter(key="registration.trial_enabled", value=True).update(value=False)
    cache.delete("platform_settings:v1")  # apps.platform_config.services.CACHE_KEY


class Migration(migrations.Migration):
    dependencies = [("platform_config", "0005_aidra_brand")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
