from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0004_directmessage_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmessage',
            name='shared_post',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='shared_messages',
                to='app.post',
            ),
        ),
    ]
