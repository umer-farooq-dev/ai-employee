"""The transfer tool now also hands live chats (website chat, WhatsApp) to people; its seeded description said
"phone call" only. Changed only while it is still the seeded text."""

from django.db import migrations

OLD = (
    "On a phone call, connect the customer to a human agent when they ask for a person or you cannot help. "
    "Say one short sentence first (e.g. you are connecting them)."
)
NEW = (
    "On a phone call or a live chat, hand the customer to a human agent when they ask for a person or you cannot "
    "help. Say one short sentence first (e.g. you are connecting them)."
)


def update(apps, schema_editor):
    apps.get_model("roles_tools", "Tool").objects.filter(key="transfer_call", description=OLD).update(description=NEW)


class Migration(migrations.Migration):
    dependencies = [("whatsapp", "0002_seed")]
    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
