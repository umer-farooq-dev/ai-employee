"""Row-level security for tickets; the support e-mails (team inbox and replies to the company). Editable in Super
Admin → Email Templates."""

from django.db import migrations

from apps.core.sql import tenant_rls

EMAILS = [
    (
        "support/team",
        "Support ticket (platform team)",
        "[{{ number }}] {{ company_name }}: {{ subject }}",
        "<p><strong>{{ company_name }}</strong> wrote on ticket {{ number }} ({{ priority }} priority):</p>"
        "<blockquote>{{ text|linebreaksbr }}</blockquote><p><a href=\"{{ url }}\">Open the ticket</a></p>",
        ["number", "subject", "company_name", "priority", "text", "url"],
    ),
    (
        "support/reply",
        "Support replied (company)",
        "[{{ number }}] {{ subject }}",
        "<p>Hello {{ name }},</p><p>Our support team replied to your ticket <strong>{{ number }}</strong>:</p>"
        "<blockquote>{{ text|linebreaksbr }}</blockquote><p>Status: {{ status }}</p>"
        '<p><a href="{{ url }}">Reply in the panel</a></p>',
        ["name", "number", "subject", "text", "status", "url"],
    ),
]


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body, variables in EMAILS:
        EmailTemplate.objects.get_or_create(
            key=key, defaults={"name": name, "subject": subject, "body_html": body, "variables": variables}
        )


class Migration(migrations.Migration):
    dependencies = [("support", "0001_initial"), ("notifications", "0008_support_kind")]
    operations = [
        tenant_rls("support_ticket"),
        tenant_rls("support_ticketmessage"),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
