from django.db import migrations, models

# Грузы не продлевают никогда: груз доставлен — полис закрыт.
CARGO_NAME = "Грузы"


def mark_cargo(apps, schema_editor):
    InsuranceType = apps.get_model("insurers", "InsuranceType")
    InsuranceType.objects.filter(name=CARGO_NAME).update(needs_prolongation=False)


class Migration(migrations.Migration):
    dependencies = [
        ("insurers", "0014_create_osago_insurance_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="insurancetype",
            name="needs_prolongation",
            field=models.BooleanField(
                default=True,
                help_text="Снимите, если полисы этого вида не продлеваются (например, грузы: груз доставлен — продлевать нечего). Такие полисы не попадают в раздел и экспорт «Пролонгация» и в метрики продлений.",
                verbose_name="Требует пролонгации",
            ),
        ),
        migrations.RunPython(mark_cargo, migrations.RunPython.noop),
    ]
