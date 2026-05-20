from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insurers", "0010_branch_add_coordinates"),
    ]

    operations = [
        migrations.AddField(
            model_name="insurer",
            name="email_primary",
            field=models.EmailField(
                blank=True, max_length=254, verbose_name="Email (основной)"
            ),
        ),
        migrations.AddField(
            model_name="insurer",
            name="email_secondary",
            field=models.EmailField(
                blank=True, max_length=254, verbose_name="Email (дополнительный)"
            ),
        ),
    ]
