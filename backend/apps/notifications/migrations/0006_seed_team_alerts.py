"""Row-level security for alerts; the alert e-mails (hot lead, campaign finished, usage); the push providers (switched
off, no key: the Web Push key pair is generated when Super Admin saves it); the WhatsApp "Alert to your team" library
template. Everything is editable in Super Admin afterwards."""

from django.db import migrations

from apps.core.sql import tenant_rls

LINK = '<p><a href="{{ url }}">Open in the panel</a></p>'
EMAILS = [
    (
        "alerts/hot_lead",
        "Hot lead (team)",
        "Hot lead: {{ lead_name|default:lead_reference }} — score {{ score }}",
        "<p>Hello {{ name }},</p><p><strong>{{ lead_name|default:'A customer' }}</strong> ({{ lead_reference }}"
        "{% if lead_phone %}, {{ lead_phone }}{% endif %}) is now a <strong>hot lead</strong> — score {{ score }}."
        "</p>{% if reason %}<p>Why: {{ reason }}</p>{% endif %}" + LINK,
        ["name", "lead_name", "lead_reference", "lead_phone", "score", "reason", "url"],
    ),
    (
        "alerts/campaign_finished",
        "Campaign finished (team)",
        "Campaign finished: {{ campaign_name }}",
        "<p>Hello {{ name }},</p><p>The campaign <strong>{{ campaign_name }}</strong> has finished.</p>"
        "<p>Leads: {{ total }} · connected: {{ connected }} · qualified: {{ qualified }} · hot: {{ hot }} · "
        "appointments: {{ appointments }} · failed: {{ failed }} · skipped: {{ skipped }}</p>" + LINK,
        [
            "name",
            "campaign_name",
            "total",
            "connected",
            "qualified",
            "hot",
            "appointments",
            "failed",
            "skipped",
            "url",
        ],
    ),
    (
        "alerts/usage",
        "Usage alert (team)",
        "{{ company_name }}: {{ percent }}% of your {{ limit_label }} used",
        "<p>Hello {{ name }},</p><p>{{ company_name }} has used <strong>{{ used }} of {{ cap }}</strong> "
        "{{ limit_label }} this month ({{ percent }}%).</p><p>When the limit is reached the AI Employees stop "
        "using it until next month or until you upgrade the plan.</p>" + LINK,
        ["name", "company_name", "limit_label", "used", "cap", "percent", "url"],
    ),
]

TEAM_ALERT = {
    "name": "team_alert",
    "title": "Alert to your team",
    "purpose": "team_alert",
    "category": "UTILITY",
    "header_type": "none",
    "variables": ["company.name", "text"],
    "texts": {
        "en": {"body": "{{1}} alert: {{2}}"},
        "hi": {"body": "{{1}} सूचना: {{2}}"},
        "bn": {"body": "{{1}} সতর্কবার্তা: {{2}}"},
    },
}


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body, variables in EMAILS:
        EmailTemplate.objects.get_or_create(
            key=key, defaults={"name": name, "subject": subject, "body_html": body, "variables": variables}
        )
    Provider = apps.get_model("providers", "Provider")
    start = (Provider.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0) + 10
    for i, (key, name, vendor, base, desc) in enumerate(
        [
            ("web-push", "Web Push", "web_push", "https://push.invalid", "Alerts to browsers and the installed app"),
            (
                "firebase",
                "Firebase Cloud Messaging",
                "fcm",
                "https://fcm.googleapis.com",
                "Alerts to the Android / iPhone app",
            ),
        ]
    ):
        Provider.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "vendor": vendor,
                "base_url": base,
                "description": desc,
                "capabilities": ["push"],
                "sort_order": start + i * 10,
            },
        )
    DefaultTemplate = apps.get_model("whatsapp", "DefaultTemplate")
    last = DefaultTemplate.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    DefaultTemplate.objects.get_or_create(name=TEAM_ALERT["name"], defaults={**TEAM_ALERT, "sort_order": last + 10})


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0005_team_alerts"),
        ("whatsapp", "0005_team_alerts"),
        ("providers", "0007_provider_webhook_secret"),
    ]
    operations = [
        tenant_rls("notifications_notification"),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
