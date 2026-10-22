"""Row-level security for the company billing tables, the billing e-mails (NOTI-01) and the Razorpay provider row
(switched off, no key: the client enters its keys in Super Admin). All editable in Super Admin."""

from django.db import migrations

from apps.core.sql import tenant_rls

LINK = '<p><a href="{{ url }}">Open Billing</a></p>'
EMAILS = [
    (
        "billing/invoice",
        "Invoice / payment receipt",
        "Invoice {{ invoice_number }} — {{ amount }} paid",
        "<p>Hello,</p><p>Thank you. We received <strong>{{ amount }}</strong> from {{ company_name }} for "
        "{{ description }}.</p><p>Your GST invoice {{ invoice_number }} is attached.</p>" + LINK,
        ["company_name", "invoice_number", "amount", "description", "url"],
    ),
    (
        "billing/invoice_due",
        "Invoice issued (pay by due date)",
        "Invoice {{ invoice_number }} — {{ amount }} due by {{ due_date }}",
        "<p>Hello,</p><p>Invoice <strong>{{ invoice_number }}</strong> for {{ description }} is attached: "
        "<strong>{{ amount }}</strong>, due by {{ due_date }}.</p><p>You can pay online in Billing.</p>" + LINK,
        ["company_name", "invoice_number", "amount", "description", "due_date", "url"],
    ),
    (
        "billing/payment_failed",
        "Payment failed",
        "Payment failed for {{ company_name }}",
        "<p>Hello,</p><p>We could not collect <strong>{{ amount }}</strong> for your {{ plan_name }} plan"
        "{% if reason %} ({{ reason }}){% endif %}.</p><p>Your AI Employees keep working until {{ grace_until }}. "
        "Please update your payment method or pay in Billing before then.</p>" + LINK,
        ["company_name", "plan_name", "amount", "reason", "grace_until", "url"],
    ),
    (
        "billing/trial_ending",
        "Trial ending soon",
        "Your free trial ends on {{ trial_end }}",
        "<p>Hello,</p><p>The free trial of {{ company_name }} ends on <strong>{{ trial_end }}</strong>. Choose a "
        "plan to keep your AI Employees working without a break.</p>" + LINK,
        ["company_name", "trial_end", "url"],
    ),
    (
        "billing/on_hold",
        "Account on hold (unpaid)",
        "{{ company_name }}: AI Employees paused",
        "<p>Hello,</p><p>{{ reason }} Your AI Employees are paused and your team can only open Billing until the "
        "subscription is paid. Your data is safe.</p>" + LINK,
        ["company_name", "reason", "url"],
    ),
    (
        "billing/plan_changed",
        "Plan changed",
        "{{ company_name }}: {{ summary }}",
        "<p>Hello,</p><p>{{ summary }}.</p>" + LINK,
        ["company_name", "summary", "url"],
    ),
]


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body, variables in EMAILS:
        EmailTemplate.objects.get_or_create(
            key=key, defaults={"name": name, "subject": subject, "body_html": body, "variables": variables}
        )
    Provider = apps.get_model("providers", "Provider")
    last = Provider.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    Provider.objects.get_or_create(
        key="razorpay",
        defaults={
            "name": "Razorpay",
            "vendor": "razorpay",
            "base_url": "https://api.razorpay.com",
            "description": "Subscriptions, renewals and invoice payments",
            "capabilities": ["payments"],
            "sort_order": last + 10,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0005_phase7_billing"),
        ("notifications", "0006_seed_team_alerts"),
        ("providers", "0007_provider_webhook_secret"),
    ]
    operations = [
        tenant_rls("billing_subscription"),
        tenant_rls("billing_invoice"),
        tenant_rls("billing_payment"),
        tenant_rls("billing_creditadjustment"),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
