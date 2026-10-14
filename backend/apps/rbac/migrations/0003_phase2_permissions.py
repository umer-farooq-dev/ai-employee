from django.db import migrations

# Phase 2 permission keys added to the existing seed roles (roles edited in Super Admin keep their other keys).
ADD = {
    ("platform", "super_admin"): ["companies.approve", "industries.manage", "enquiries.view", "enquiries.manage"],
    ("platform", "support"): ["enquiries.view", "enquiries.manage"],
}


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for (scope, key), keys in ADD.items():
        role = Role.objects.filter(scope=scope, key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0002_seed_roles")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
