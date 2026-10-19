from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0003_directmessage_audio_and_optional_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmessage',
            name='attachment',
            field=models.FileField(blank=True, upload_to='chat/media/'),
        ),
    ]
