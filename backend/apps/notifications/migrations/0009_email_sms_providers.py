"""SA-10: e-mail (SMTP) and SMS (MSG91) provider rows, switched off and without keys; the client enters its own in
Super Admin → Voice & Channels. Twilio can also send SMS once its SMS sender number is filled in."""

from django.db import migrations

ROWS = [
    ("smtp", "E-mail (SMTP)", "smtp", "https://smtp.invalid", "Every e-mail of the platform", ["email"]),
    ("msg91", "MSG91", "msg91", "https://api.msg91.com", "SMS: mobile OTP", ["sms"]),
]


def seed(apps, schema_editor):
    Provider = apps.get_model("providers", "Provider")
    last = Provider.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    for i, (key, name, vendor, base, desc, caps) in enumerate(ROWS, 1):
        Provider.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "vendor": vendor,
                "base_url": base,
                "description": desc,
                "capabilities": caps,
                "sort_order": last + i * 10,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0008_support_kind"), ("billing", "0006_rls_and_emails")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
