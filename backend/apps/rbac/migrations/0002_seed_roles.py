from django.db import migrations

from apps.rbac.catalog import SEED_ROLES


def seed(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for scope, key, name, permissions in SEED_ROLES:
        Role.objects.get_or_create(scope=scope, key=key,
                                   defaults={"name": name, "permissions": list(permissions), "is_system": True})


class Migration(migrations.Migration):
    dependencies = [("rbac", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
