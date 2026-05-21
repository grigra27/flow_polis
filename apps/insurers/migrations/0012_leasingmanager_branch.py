from collections import Counter

from django.db import migrations, models
import django.db.models.deletion


def backfill_manager_branch(apps, schema_editor):
    """
    Заполняем LeasingManager.branch перед тем, как сделать поле NOT NULL.

    Источник данных:
    1. Самый частый филиал среди полисов менеджера (Policy.branch).
    2. Если у менеджера нет полисов — первый филиал по алфавиту (детерминированный fallback).

    Если в системе нет ни одного филиала, миграция падает: добавлять обязательный FK
    без целевых значений некуда.
    """

    LeasingManager = apps.get_model("insurers", "LeasingManager")
    Branch = apps.get_model("insurers", "Branch")
    Policy = apps.get_model("policies", "Policy")

    managers = LeasingManager.objects.all()
    if not managers.exists():
        return

    fallback_branch = Branch.objects.order_by("branch_name").first()
    if fallback_branch is None:
        raise RuntimeError(
            "Невозможно сделать LeasingManager.branch обязательным: "
            "в таблице insurers_branch нет ни одной записи. "
            "Создайте филиал или загрузите fixtures/initial_data.json."
        )

    for manager in managers:
        branch_ids = list(
            Policy.objects.filter(leasing_manager=manager)
            .exclude(branch__isnull=True)
            .values_list("branch_id", flat=True)
        )
        if branch_ids:
            most_common_branch_id, _ = Counter(branch_ids).most_common(1)[0]
            manager.branch_id = most_common_branch_id
        else:
            manager.branch_id = fallback_branch.pk
        manager.save(update_fields=["branch"])


class Migration(migrations.Migration):
    dependencies = [
        ("insurers", "0011_insurer_email_primary_insurer_email_secondary"),
        ("policies", "0020_paymentschedule_alliance_paid"),
    ]

    operations = [
        migrations.AddField(
            model_name="leasingmanager",
            name="branch",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="leasing_managers",
                to="insurers.branch",
                verbose_name="Филиал",
            ),
        ),
        migrations.RunPython(
            backfill_manager_branch,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="leasingmanager",
            name="branch",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="leasing_managers",
                to="insurers.branch",
                verbose_name="Филиал",
            ),
        ),
    ]
