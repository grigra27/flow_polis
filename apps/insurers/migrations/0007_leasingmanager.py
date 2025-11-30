# Generated migration for LeasingManager model

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insurers", "0006_insurancetype_icon"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeasingManager",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        max_length=255, unique=True, verbose_name="ФИО менеджера"
                    ),
                ),
                (
                    "phone",
                    models.CharField(blank=True, max_length=50, verbose_name="Телефон"),
                ),
                (
                    "email",
                    models.EmailField(blank=True, max_length=254, verbose_name="Email"),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Примечание")),
            ],
            options={
                "verbose_name": "Менеджер лизинговой компании",
                "verbose_name_plural": "Менеджеры лизинговой компании",
                "ordering": ["name"],
            },
        ),
    ]
