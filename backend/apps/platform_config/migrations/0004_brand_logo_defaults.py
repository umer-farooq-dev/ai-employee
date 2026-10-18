"""Default logos / favicon were the purchased templates' own (eSoft / Rizz). Switch rows still on those defaults to the
neutral "AI Employee" marks in static/brand; a logo uploaded in General Settings is left alone."""

from django.core.cache import cache
from django.db import migrations

SWAP = {
    "general.logo_light": ("/static/panel/images/logo-light.png", "/static/brand/logo-light.svg"),
    "general.logo_dark": ("/static/website/img/logo/header-logo2.png", "/static/brand/logo-dark.svg"),
    "general.logo_small": ("/static/panel/images/logo-sm.png", "/static/brand/logo-sm.svg"),
    "general.favicon": ("/static/panel/images/favicon.ico", "/static/brand/favicon.svg"),
}


def swap(apps, schema_editor):
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for key, (old, new) in SWAP.items():
        PlatformSetting.objects.filter(key=key, value=old).update(value=new)
    cache.delete("platform_settings:v1")  # apps.platform_config.services.CACHE_KEY


class Migration(migrations.Migration):
    dependencies = [("platform_config", "0003_seed_phase2_settings")]
    operations = [migrations.RunPython(swap, migrations.RunPython.noop)]
