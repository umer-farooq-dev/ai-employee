from django.db import migrations

from apps.notifications.seeds import SEED_TEMPLATES


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body, variables in SEED_TEMPLATES:
        EmailTemplate.objects.get_or_create(key=key, defaults={"name": name, "subject": subject, "body_html": body,
                                                               "variables": variables})


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
