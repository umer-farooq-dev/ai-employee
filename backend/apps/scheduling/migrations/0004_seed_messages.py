"""Row-level security for appointment notices; the appointment e-mails (CAL-07 customer, CAL-10 team) and the
"appointment cancelled" WhatsApp library template. All editable in Super Admin afterwards."""

from django.db import migrations

from apps.core.sql import tenant_rls

HELLO = "<p>Hello{% if lead_name %} {{ lead_name }}{% endif %},</p>"
DETAILS = (
    "<p><strong>{{ appointment_type }}</strong> ({{ appointment_number }})<br>{{ appointment_time }}<br>"
    "{{ appointment_location }}{% if meeting_link %}<br><a href=\"{{ meeting_link }}\">Join the meeting</a>"
    "{% endif %}</p>"
)
SIGN = "<p>Regards,<br>{{ company_name }}</p>"
CUSTOMER_VARS = [
    "lead_name",
    "company_name",
    "appointment_type",
    "appointment_number",
    "appointment_time",
    "appointment_location",
    "meeting_link",
    "calendar_name",
]

EMAILS = [
    (
        "appointment/confirmation",
        "Appointment confirmed (customer)",
        "Your {{ appointment_type }} is confirmed — {{ appointment_time }}",
        HELLO + "<p>Your appointment with {{ company_name }} is confirmed.</p>" + DETAILS + SIGN,
        CUSTOMER_VARS,
    ),
    (
        "appointment/rescheduled",
        "Appointment moved (customer)",
        "New time for your {{ appointment_type }} — {{ appointment_time }}",
        HELLO
        + "<p>Your appointment with {{ company_name }} has a new time{% if old_time %} (it was {{ old_time }})"
        "{% endif %}.</p>"
        + DETAILS
        + SIGN,
        [*CUSTOMER_VARS, "old_time"],
    ),
    (
        "appointment/cancelled",
        "Appointment cancelled (customer)",
        "Your {{ appointment_type }} on {{ appointment_time }} is cancelled",
        HELLO
        + "<p>Your {{ appointment_type }} ({{ appointment_number }}) on {{ appointment_time }} is cancelled. "
        "Reply to this e-mail or call us to book a new time.</p>"
        + SIGN,
        [*CUSTOMER_VARS, "reason"],
    ),
    (
        "appointment/reminder",
        "Appointment reminder (customer)",
        "Reminder: {{ appointment_type }} — {{ appointment_time }}",
        HELLO + "<p>This is a reminder of your appointment with {{ company_name }}.</p>" + DETAILS + SIGN,
        CUSTOMER_VARS,
    ),
    (
        "appointment/staff_notice",
        "Booking new / moved / cancelled (team)",
        "{% if event == 'booked' %}New booking{% elif event == 'rescheduled' %}Booking moved{% else %}Booking "
        "cancelled{% endif %}: {{ appointment_type }} — {{ appointment_time }}",
        "<p>Hello {{ name }},</p><p>{% if event == 'booked' %}A new appointment was booked with you"
        "{% elif event == 'rescheduled' %}An appointment with you was moved{% if old_time %} from {{ old_time }}"
        "{% endif %}{% else %}An appointment with you was cancelled{% if reason %}: {{ reason }}{% endif %}{% endif %}"
        " by {{ changed_by|default:'the AI Employee' }}.</p>"
        + DETAILS
        + "<p>Customer: {{ lead_name|default:'—' }} {{ lead_phone }} {{ lead_reference }}</p>"
        "<p><a href=\"{{ appointment_url }}\">Open the appointment</a></p>",
        [
            *CUSTOMER_VARS,
            "name",
            "event",
            "changed_by",
            "old_time",
            "reason",
            "lead_phone",
            "lead_reference",
            "appointment_url",
        ],
    ),
]

CANCELLED = {
    "name": "appointment_cancelled",
    "title": "Appointment cancelled",
    "purpose": "appointment_cancelled",
    "category": "UTILITY",
    "header_type": "none",
    "variables": ["lead.name", "appointment.type", "appointment.when", "appointment.number"],
    "texts": {
        "en": {"body": "Hello {{1}}, your {{2}} on {{3}} (booking {{4}}) is cancelled. Reply here to book a new time."},
        "hi": {"body": "नमस्ते {{1}}, {{3}} की आपकी {{2}} (बुकिंग {{4}}) रद्द कर दी गई है। नया समय बुक करने के लिए यहीं जवाब दें।"},
        "bn": {"body": "নমস্কার {{1}}, {{3}}-এর আপনার {{2}} (বুকিং {{4}}) বাতিল করা হয়েছে। নতুন সময় বুক করতে এখানে উত্তর দিন।"},
    },
}


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body, variables in EMAILS:
        EmailTemplate.objects.get_or_create(
            key=key, defaults={"name": name, "subject": subject, "body_html": body, "variables": variables}
        )
    DefaultTemplate = apps.get_model("whatsapp", "DefaultTemplate")
    last = DefaultTemplate.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    DefaultTemplate.objects.get_or_create(name=CANCELLED["name"], defaults={**CANCELLED, "sort_order": last + 10})


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0003_appointment_notices"),
        ("whatsapp", "0004_appointment_notices"),
        ("notifications", "0004_seed_phase3_templates"),
    ]
    operations = [
        tenant_rls("scheduling_appointmentnotice"),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
