"""The seeded AI disclosure said "This call may be recorded" — wrong on chats and on calls without recording. The
recording announcement is its own language phrase (said only when recording is on, REC-03). Only texts still equal
to the original seed are changed; texts edited in Super Admin are kept."""

from django.db import migrations

OLD = {
    "en": "I am {{ employee_name }}, an AI assistant for {{ company_name }}. This call may be recorded.",
    "hi": "मैं {{ employee_name }}, {{ company_name }} की AI सहायक हूँ। यह कॉल रिकॉर्ड हो सकती है।",
    "bn": "আমি {{ employee_name }}, {{ company_name }}-এর একজন AI সহকারী। এই কলটি রেকর্ড করা হতে পারে।",
}
NEW = {
    "en": "I am {{ employee_name }}, an AI assistant for {{ company_name }}.",
    "hi": "मैं {{ employee_name }}, {{ company_name }} की AI सहायक हूँ।",
    "bn": "আমি {{ employee_name }}, {{ company_name }}-এর একজন AI সহকারী।",
}


def fix(apps, schema_editor):
    TemplateVersion = apps.get_model("industries", "TemplateVersion")
    for version in TemplateVersion.objects.all():
        texts = dict(version.disclosure_texts or {})
        changed = {code: NEW[code] for code, text in texts.items() if OLD.get(code) == text}
        if changed:
            version.disclosure_texts = {**texts, **changed}
            version.save(update_fields=["disclosure_texts"])


class Migration(migrations.Migration):
    dependencies = [("industries", "0007_help_texts")]
    operations = [migrations.RunPython(fix, migrations.RunPython.noop)]
