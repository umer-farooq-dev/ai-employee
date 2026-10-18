"""Education's seeded icon was a white glyph (invisible on the light card); use the coloured one from the same set
as Real Estate / Travel. An icon changed in Super Admin is left alone."""

from django.db import migrations

OLD, NEW = "/static/website/img/icons/features-icon3.png", "/static/website/img/icons/service3-icon5.png"


def swap(apps, schema_editor):
    apps.get_model("industries", "Industry").objects.filter(key="education", icon=OLD).update(icon=NEW)


class Migration(migrations.Migration):
    dependencies = [("industries", "0005_shared_rls")]
    operations = [migrations.RunPython(swap, migrations.RunPython.noop)]
