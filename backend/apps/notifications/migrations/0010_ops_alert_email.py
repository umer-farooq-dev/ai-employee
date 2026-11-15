"""ENGR-05: the platform alert e-mail (ops_watch). Editable in Super Admin → Email Templates."""

from django.db import migrations


def seed(apps, schema_editor):
    apps.get_model("notifications", "EmailTemplate").objects.get_or_create(
        key="ops/alert",
        defaults={
            "name": "Platform alert (operations team)",
            "subject": "[{{ environment }}] {{ title }}",
            "body_html": "<p><strong>{{ title }}</strong> ({{ environment }})</p>"
            "<pre style=\"white-space:pre-wrap\">{{ details }}</pre>"
            "<p>Super Admin → Logs shows the details. This alert repeats after the cool-down in System Settings → "
            "Monitoring &amp; alerts while the problem lasts.</p>",
            "variables": ["title", "details", "environment"],
        },
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0009_email_sms_providers")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
