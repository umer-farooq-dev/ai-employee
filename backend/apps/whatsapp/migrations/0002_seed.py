"""Row-level security for the company tables; the Meta WhatsApp Cloud API vendor (switched off, no key); the
send_whatsapp tool (TOOL-09) for the roles and templates that follow up with customers; the default template library
and the WhatsApp language phrases. Everything is editable in Super Admin afterwards."""

from django.db import migrations

from apps.core.sql import tenant_rls

ROLES = ["sales_executive", "receptionist", "customer_support", "follow_up"]

LIBRARY = [
    {
        "name": "lead_follow_up",
        "title": "Lead follow-up",
        "purpose": "lead_follow_up",
        "category": "UTILITY",
        "header_type": "none",
        "variables": ["lead.name", "company.name"],
        "texts": {
            "en": {
                "body": "Hello {{1}}, thank you for speaking with {{2}} today. Reply here if you have any questions — "
                "we are happy to help."
            },
            "hi": {"body": "नमस्ते {{1}}, आज {{2}} से बात करने के लिए धन्यवाद। कोई भी सवाल हो तो यहीं जवाब दें — हम मदद के लिए तैयार हैं।"},
            "bn": {"body": "নমস্কার {{1}}, আজ {{2}}-এর সঙ্গে কথা বলার জন্য ধন্যবাদ। কোনো প্রশ্ন থাকলে এখানে উত্তর দিন — আমরা সাহায্য করতে প্রস্তুত।"},
        },
    },
    {
        "name": "appointment_confirmation",
        "title": "Appointment confirmation",
        "purpose": "appointment_confirmation",
        "category": "UTILITY",
        "header_type": "none",
        "variables": ["lead.name", "appointment.type", "appointment.when", "appointment.number"],
        "texts": {
            "en": {"body": "Hello {{1}}, your {{2}} is confirmed for {{3}}. Booking number: {{4}}. Reply here to change it."},
            "hi": {"body": "नमस्ते {{1}}, आपकी {{2}} {{3}} के लिए पक्की हो गई है। बुकिंग नंबर: {{4}}। बदलाव के लिए यहीं जवाब दें।"},
            "bn": {"body": "নমস্কার {{1}}, আপনার {{2}} {{3}}-এ নিশ্চিত হয়েছে। বুকিং নম্বর: {{4}}। পরিবর্তনের জন্য এখানে উত্তর দিন।"},
        },
    },
    {
        "name": "appointment_reminder",
        "title": "Appointment reminder",
        "purpose": "appointment_reminder",
        "category": "UTILITY",
        "header_type": "none",
        "variables": ["appointment.type", "company.name", "appointment.when", "appointment.number"],
        "texts": {
            "en": {"body": "Reminder: your {{1}} with {{2}} is on {{3}}. Booking number {{4}}. Reply here to reschedule."},
            "hi": {"body": "याद दिलाना: {{2}} के साथ आपकी {{1}} {{3}} को है। बुकिंग नंबर {{4}}। समय बदलने के लिए यहीं जवाब दें।"},
            "bn": {"body": "মনে করিয়ে দিচ্ছি: {{2}}-এর সঙ্গে আপনার {{1}} {{3}}-এ। বুকিং নম্বর {{4}}। সময় বদলাতে এখানে উত্তর দিন।"},
        },
    },
    {
        "name": "item_details",
        "title": "Property / product details with photo",
        "purpose": "item_info",
        "category": "UTILITY",
        "header_type": "image",
        "variables": ["lead.name", "item.title", "item.price"],
        "texts": {
            "en": {"body": "Hello {{1}}, here are the details of {{2}} ({{3}}). Reply here to book a visit or ask anything."},
            "hi": {"body": "नमस्ते {{1}}, {{2}} ({{3}}) की जानकारी यह रही। विज़िट बुक करने या कुछ भी पूछने के लिए यहीं जवाब दें।"},
            "bn": {"body": "নমস্কার {{1}}, এই হলো {{2}} ({{3}})-এর বিস্তারিত। ভিজিট বুক করতে বা কিছু জানতে এখানে উত্তর দিন।"},
        },
    },
    {
        "name": "callback_confirmation",
        "title": "Callback confirmation",
        "purpose": "callback",
        "category": "UTILITY",
        "header_type": "none",
        "variables": ["lead.name", "company.name"],
        "texts": {
            "en": {"body": "Hello {{1}}, we received your callback request. Our team at {{2}} will call you soon."},
            "hi": {"body": "नमस्ते {{1}}, हमें आपका कॉल बैक अनुरोध मिल गया है। {{2}} की टीम जल्द ही आपको कॉल करेगी।"},
            "bn": {"body": "নমস্কার {{1}}, আপনার কলব্যাকের অনুরোধ পেয়েছি। {{2}}-এর টিম শীঘ্রই আপনাকে ফোন করবে।"},
        },
    },
]

PHRASES = {
    "en": {
        "wa_opted_out": "You will not receive WhatsApp messages from us anymore. Reply START to subscribe again.",
        "wa_opted_in": "Thank you! You will receive WhatsApp updates from us again.",
    },
    "hi": {
        "wa_opted_out": "अब आपको हमारी ओर से WhatsApp संदेश नहीं मिलेंगे। फिर से जुड़ने के लिए START लिखें।",
        "wa_opted_in": "धन्यवाद! आपको फिर से हमारी ओर से WhatsApp अपडेट मिलेंगे।",
    },
    "bn": {
        "wa_opted_out": "আপনি আর আমাদের থেকে WhatsApp বার্তা পাবেন না। আবার যুক্ত হতে START লিখুন।",
        "wa_opted_in": "ধন্যবাদ! আপনি আবার আমাদের থেকে WhatsApp আপডেট পাবেন।",
    },
}


def seed(apps, schema_editor):
    Provider = apps.get_model("providers", "Provider")
    start = (Provider.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0) + 10
    Provider.objects.get_or_create(
        key="meta-whatsapp",
        defaults={
            "name": "Meta WhatsApp Cloud API",
            "description": "Official WhatsApp Business Platform: messages, templates, delivery status",
            "vendor": "meta_whatsapp",
            "base_url": "https://graph.facebook.com/v21.0",
            "capabilities": ["whatsapp"],
            "sort_order": start,
        },
    )
    Tool = apps.get_model("roles_tools", "Tool")
    Tool.objects.get_or_create(
        key="send_whatsapp",
        defaults={
            "name": "Send on WhatsApp",
            "category": "communication",
            "handler": "send_whatsapp",
            "side_effect": "external",
            "config": {},
            "description": "Send the customer details on WhatsApp: in a WhatsApp chat the photos, brochure and "
            "location of an item (item_id); on calls and other chats an approved template. Ask the customer first.",
            "sort_order": 125,
        },
    )
    Role = apps.get_model("roles_tools", "EmployeeRole")
    for role in Role.objects.filter(key__in=ROLES):
        if role.allowed_tools and "send_whatsapp" not in role.allowed_tools:
            role.allowed_tools = [*role.allowed_tools, "send_whatsapp"]
            role.save(update_fields=["allowed_tools"])
    Version = apps.get_model("industries", "TemplateVersion")
    for version in Version.objects.all():
        if version.enabled_tools and "send_whatsapp" not in version.enabled_tools:
            version.enabled_tools = [*version.enabled_tools, "send_whatsapp"]
            version.save(update_fields=["enabled_tools"])
    DefaultTemplate = apps.get_model("whatsapp", "DefaultTemplate")
    for i, row in enumerate(LIBRARY):
        DefaultTemplate.objects.get_or_create(name=row["name"], defaults={**row, "sort_order": (i + 1) * 10})
    Language = apps.get_model("providers", "Language")
    for code, texts in PHRASES.items():
        lang = Language.objects.filter(code=code).first()
        if lang:
            lang.texts = {**texts, **{k: v for k, v in (lang.texts or {}).items() if v}}
            lang.save(update_fields=["texts"])


class Migration(migrations.Migration):
    dependencies = [
        ("whatsapp", "0001_initial"),
        ("providers", "0007_provider_webhook_secret"),
        ("roles_tools", "0004_help_texts"),
        ("industries", "0008_disclosure_without_recording"),
    ]
    operations = [
        tenant_rls("whatsapp_template"),
        tenant_rls("whatsapp_wamessage"),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
