from django.db import migrations, models


def mark_existing_messages_as_read(apps, schema_editor):
    DirectMessage = apps.get_model('app', 'DirectMessage')
    DirectMessage.objects.using(schema_editor.connection.alias).update(is_read=True)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmessage',
            name='is_read',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            mark_existing_messages_as_read,
            migrations.RunPython.noop,
        ),
    ]
