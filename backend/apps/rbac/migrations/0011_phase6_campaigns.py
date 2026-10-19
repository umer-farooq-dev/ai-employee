from django.db import migrations

OWNER = ["campaigns.view", "campaigns.manage", "campaigns.approve"]
MANAGER = ["campaigns.view", "campaigns.manage"]


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for key, keys in (("owner", OWNER), ("manager", MANAGER)):
        role = Role.objects.filter(scope="company", key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0010_phase6_whatsapp")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
