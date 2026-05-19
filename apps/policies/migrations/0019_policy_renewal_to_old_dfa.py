from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("policies", "0018_paymentschedule_policies_pa_paid_da_4940dc_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="policy",
            name="renewal_to_old_dfa",
            field=models.BooleanField(
                default=False, verbose_name="Перезаключение (к старому ДФА)"
            ),
        ),
    ]
