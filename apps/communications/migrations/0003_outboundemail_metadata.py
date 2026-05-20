from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("communications", "0002_alter_outboundemail_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="outboundemail",
            name="metadata",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="Служебные данные"
            ),
        ),
    ]
