from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0002_directmessage_is_read'),
    ]

    operations = [
        migrations.AlterField(
            model_name='directmessage',
            name='text',
            field=models.CharField(blank=True, max_length=4000),
        ),
        migrations.AddField(
            model_name='directmessage',
            name='audio',
            field=models.FileField(blank=True, upload_to='chat/audio/'),
        ),
    ]
