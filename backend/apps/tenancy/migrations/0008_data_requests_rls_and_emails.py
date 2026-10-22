"""Row-level security for data requests and the privacy e-mails (TEN-07). Editable in Super Admin."""

from django.db import migrations

from apps.core.sql import tenant_rls

EMAILS = [
    (
        "privacy/export_ready",
        "Data export ready",
        "{{ company_name }}: your data export is ready",
        '<p>Hello,</p><p>The full data export of {{ company_name }} is ready. <a href="{{ url }}">Download it</a> '
        "(sign-in needed) until {{ expires }}.</p>",
        ["company_name", "url", "expires"],
    ),
    (
        "privacy/deletion_scheduled",
        "Account deletion scheduled",
        "{{ company_name }} will be deleted on {{ date }}",
        "<p>Hello,</p><p>The account of {{ company_name }} and all its data will be permanently deleted on "
        "<strong>{{ date }}</strong>. To keep it, cancel the deletion in Settings → Data &amp; privacy before then. "
        "Download a data export first if you need a copy.</p>",
        ["company_name", "date"],
    ),
]


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body, variables in EMAILS:
        EmailTemplate.objects.get_or_create(
            key=key, defaults={"name": name, "subject": subject, "body_html": body, "variables": variables}
        )


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0007_data_requests"), ("notifications", "0008_support_kind")]
    operations = [tenant_rls("tenancy_datarequest"), migrations.RunPython(seed, migrations.RunPython.noop)]
