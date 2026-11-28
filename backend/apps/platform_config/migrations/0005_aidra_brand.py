"""The platform is named Aidra: settings still on the old "AI Employee" defaults move to the Aidra name and its 3D marks
in static/brand (aidra-*); a name or logo changed in General Settings is left alone."""

from django.core.cache import cache
from django.db import migrations

SWAP = {
    "general.platform_name": ("AI Employee", "Aidra"),
    "general.short_name": ("AIE", "Aidra"),
    "general.logo_light": ("/static/brand/logo-light.svg", "/static/brand/aidra-logo-light.svg"),
    "general.logo_dark": ("/static/brand/logo-dark.svg", "/static/brand/aidra-logo-dark.svg"),
    "general.logo_small": ("/static/brand/logo-sm.svg", "/static/brand/aidra-logo-sm.svg"),
    "general.favicon": ("/static/brand/favicon.svg", "/static/brand/aidra-favicon.svg"),
    "general.widget_powered_by": ("Powered by AI Employee", "Powered by Aidra"),
    "contact.copyright": ("© {year} AI Employee", "© {year} Aidra"),
    "email.sender_name": ("AI Employee", "Aidra"),
}


def swap(apps, schema_editor):
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for key, (old, new) in SWAP.items():
        PlatformSetting.objects.filter(key=key, value=old).update(value=new)
    cache.delete("platform_settings:v1")  # apps.platform_config.services.CACHE_KEY


class Migration(migrations.Migration):
    dependencies = [("platform_config", "0004_brand_logo_defaults")]
    operations = [migrations.RunPython(swap, migrations.RunPython.noop)]
