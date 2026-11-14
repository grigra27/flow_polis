"""Новые условия ВСК после закрепления ставок всех существующих полисов."""
from datetime import date
from decimal import Decimal

from django.db import migrations


def add_vsk_versions(apps, schema_editor):
    db = schema_editor.connection.alias
    Insurer = apps.get_model("insurers", "Insurer")
    Rate = apps.get_model("insurers", "CommissionRate")
    insurers = list(Insurer.objects.using(db).filter(insurer_name="ВСК"))
    if not insurers:
        return  # Чистая установка: справочник компаний ещё не заполнен.
    if len(insurers) != 1:
        raise RuntimeError(
            "Несколько компаний ВСК: требуется проверка перед добавлением ставок."
        )
    for name, old, new in [
        ("КАСКО", "25", "30"),
        ("Имущество", "20", "25"),
        ("Спецтехника", "25", "30"),
    ]:
        original = (
            Rate.objects.using(db)
            .filter(
                insurer_id=insurers[0].pk,
                insurance_type__name=name,
                effective_from__isnull=True,
            )
            .first()
        )
        if original is None:
            continue
        if original.kv_percent != Decimal(old):
            raise RuntimeError(
                f"Исходная ставка ВСК / {name} изменилась: требуется проверка."
            )
        rate, _ = Rate.objects.using(db).get_or_create(
            insurer_id=original.insurer_id,
            insurance_type_id=original.insurance_type_id,
            effective_from=date(2026, 9, 1),
            defaults={
                "kv_percent": Decimal(new),
                "notes": "Новый договор с ВСК. С 01.09.2026 включительно; условия ранее внесённых полисов сохраняются.",
            },
        )
        if rate.kv_percent != Decimal(new):
            raise RuntimeError(
                f"Ставка ВСК / {name} с 01.09.2026 отличается: требуется проверка."
            )


class Migration(migrations.Migration):
    dependencies = [
        ("insurers", "0016_alter_commissionrate_options_and_more"),
        ("policies", "0026_policy_commission_rate_policy_commission_rate_origin"),
    ]
    # Обратный релиз не удаляет версии, на которые уже могли сослаться новые полисы.
    operations = [migrations.RunPython(add_vsk_versions, migrations.RunPython.noop)]
