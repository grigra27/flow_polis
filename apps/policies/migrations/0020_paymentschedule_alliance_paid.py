from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("policies", "0019_policy_renewal_to_old_dfa"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentschedule",
            name="alliance_paid",
            field=models.BooleanField(default=False, verbose_name="Оплатил Альянс"),
        ),
    ]
