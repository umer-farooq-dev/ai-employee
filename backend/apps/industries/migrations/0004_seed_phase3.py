from django.db import migrations
from django.utils import timezone

from apps.industries.seeds import COMMON_HANDOFF, DISCLOSURE, SOURCES, STATUSES, TEMPLATES, TRANSITIONS


def seed(apps, schema_editor):
    """CRM-02 statuses, CRM-03 sources and the published v1 of the MVP templates (IND-06)."""
    Industry = apps.get_model("industries", "Industry")
    TemplateVersion = apps.get_model("industries", "TemplateVersion")
    FieldDefinition = apps.get_model("industries", "FieldDefinition")
    CatalogType = apps.get_model("industries", "CatalogType")
    AppointmentType = apps.get_model("industries", "AppointmentType")
    LeadStatus = apps.get_model("industries", "LeadStatus")
    LeadSource = apps.get_model("industries", "LeadSource")
    ScoringRule = apps.get_model("industries", "ScoringRule")
    Company = apps.get_model("tenancy", "Company")

    for order, (key, label, color, category) in enumerate(STATUSES):
        LeadStatus.objects.get_or_create(
            key=key, template_version=None, company=None,
            defaults={"label": label, "color": color, "category": category, "sort_order": order, "is_system": True})
    for order, (key, label) in enumerate(SOURCES):
        LeadSource.objects.get_or_create(key=key, defaults={"label": label, "sort_order": order})

    for t in TEMPLATES:
        industry = Industry.objects.filter(key=t["industry"]).first()
        if not industry or TemplateVersion.objects.filter(industry=industry).exists():
            continue
        industry.supported_languages = t["languages"]
        version = TemplateVersion.objects.create(
            industry=industry, version=1, status="published", published_at=timezone.now(), notes="Initial template",
            base_instructions=t["instructions"], qualification_flow=t["qualification"], handoff_rules=COMMON_HANDOFF,
            greetings=t["greeting"], disclosure_texts=DISCLOSURE,
            default_faqs=t["faqs"], whatsapp_templates=t["whatsapp"], status_transitions=TRANSITIONS,
            score_thresholds={"hot": 70, "warm": 40},
        )
        for order, fd in enumerate(t["lead_fields"]):
            FieldDefinition.objects.create(template_version=version, entity="lead", sort_order=order, **fd)
        cat = t["catalog"]
        catalog = CatalogType.objects.create(
            template_version=version, key=cat["key"], name=cat["name"], item_label=cat["item_label"],
            display=cat.get("display", {}), match_rules=cat.get("match_rules", {}))
        for order, fd in enumerate(cat["fields"]):
            FieldDefinition.objects.create(template_version=version, entity=f"catalog:{catalog.key}", sort_order=order,
                                           **fd)
        key, name, duration, buffer, mode = t["appointment"]
        AppointmentType.objects.create(template_version=version, key=key, name=name, duration_min=duration,
                                       buffer_min=buffer, location_mode=mode, reminder_offsets=[1440, 120])
        for order, rule in enumerate(t["scoring"]):
            ScoringRule.objects.create(template_version=version, priority=order, **rule)
        industry.published_version = version
        industry.save()
        Company.objects.filter(industry=industry, template_version__isnull=True).update(template_version=version)


class Migration(migrations.Migration):
    dependencies = [
        ("industries", "0003_leadsource_industry_supported_languages_holiday_and_more"),
        ("tenancy", "0005_company_template_version"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
