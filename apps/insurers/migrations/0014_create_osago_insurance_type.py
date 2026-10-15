from django.db import migrations

OSAGO_NAME = "ОСАГО"


def create_osago_type(apps, schema_editor):
    InsuranceType = apps.get_model("insurers", "InsuranceType")
    insurance_type, _ = InsuranceType.objects.get_or_create(name=OSAGO_NAME)
    if not insurance_type.is_osago:
        insurance_type.is_osago = True
        insurance_type.save(update_fields=["is_osago"])


def remove_osago_type(apps, schema_editor):
    InsuranceType = apps.get_model("insurers", "InsuranceType")
    insurance_type = InsuranceType.objects.filter(name=OSAGO_NAME).first()
    if insurance_type is None:
        return
    if insurance_type.policies.exists() or insurance_type.commission_rates.exists():
        insurance_type.is_osago = False
        insurance_type.save(update_fields=["is_osago"])
    else:
        insurance_type.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("insurers", "0013_insurancetype_is_osago"),
    ]

    operations = [
        migrations.RunPython(create_osago_type, remove_osago_type),
    ]
