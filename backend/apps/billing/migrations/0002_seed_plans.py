from django.db import migrations

# SUB-02: seed plans from the client brief. Only prices are known; limits are left empty for Super Admin to set.
SEED_PLANS = [
    ("starter", "Starter", 299900, False, 1),
    ("business", "Business", 999900, False, 2),
    ("pro", "Pro", 2499900, False, 3),
    ("enterprise", "Enterprise", None, True, 4),
]


def seed(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for key, name, price, custom, order in SEED_PLANS:
        Plan.objects.get_or_create(key=key, defaults={"name": name, "price_monthly_paise": price, "is_custom": custom,
                                                      "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
