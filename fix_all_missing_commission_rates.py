#!/usr/bin/env python
"""
Универсальный скрипт для исправления всех платежей без commission_rate

Исправляет проблему для всех страховщиков, не только для ВСК.
"""

import os
import sys
import django

# Настройка Django окружения
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.insurers.models import CommissionRate
from apps.policies.models import PaymentSchedule
from decimal import Decimal, ROUND_HALF_UP


def main():
    print("=" * 80)
    print("ИСПРАВЛЕНИЕ ВСЕХ ПЛАТЕЖЕЙ БЕЗ COMMISSION_RATE")
    print("=" * 80)
    print()

    # Находим все платежи без commission_rate
    payments_without_rate = PaymentSchedule.objects.filter(
        commission_rate__isnull=True
    ).select_related("policy", "policy__insurance_type", "policy__insurer")

    total_count = payments_without_rate.count()

    if total_count == 0:
        print("✓ Все платежи имеют установленный commission_rate")
        print("Проблем не обнаружено!")
        return

    print(f"Найдено платежей без commission_rate: {total_count}")
    print()

    # Группируем по страховщикам
    from collections import defaultdict

    by_insurer = defaultdict(list)

    for payment in payments_without_rate:
        insurer = payment.policy.insurer
        by_insurer[insurer].append(payment)

    print(f"Затронуто страховщиков: {len(by_insurer)}")
    for insurer, payments in by_insurer.items():
        print(f"  - {insurer.insurer_name}: {len(payments)} платеж(ей)")
    print()

    # Спрашиваем подтверждение
    answer = input("Исправить все платежи? (да/нет): ").strip().lower()
    if answer not in ["да", "yes", "y", "д"]:
        print("Отменено пользователем")
        return

    print()
    print("Обработка...")
    print()

    updated_count = 0
    skipped_count = 0
    errors = []

    for insurer, payments in by_insurer.items():
        print(f"Обработка {insurer.insurer_name}...")

        # Группируем платежи по виду страхования
        by_insurance_type = defaultdict(list)
        for payment in payments:
            insurance_type = payment.policy.insurance_type
            by_insurance_type[insurance_type].append(payment)

        for insurance_type, type_payments in by_insurance_type.items():
            # Находим ставку комиссии
            try:
                rate = CommissionRate.objects.get(
                    insurer=insurer, insurance_type=insurance_type
                )

                print(f"  {insurance_type.name}: ставка {rate.kv_percent}%")

                for payment in type_payments:
                    try:
                        payment.commission_rate = rate
                        # Пересчитываем КВ в рублях и округляем до 2 знаков
                        kv_rub = payment.calculate_kv_rub()
                        payment.kv_rub = kv_rub.quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        payment.save(
                            update_fields=["commission_rate", "kv_rub", "updated_at"]
                        )
                        updated_count += 1
                    except Exception as e:
                        error_msg = f"Ошибка при обновлении платежа {payment.id}: {e}"
                        errors.append(error_msg)
                        skipped_count += 1

                print(f"    ✓ Обновлено {len(type_payments)} платеж(ей)")

            except CommissionRate.DoesNotExist:
                error_msg = f"  ✗ {insurance_type.name}: ставка комиссии не найдена!"
                print(error_msg)
                errors.append(error_msg)
                skipped_count += len(type_payments)

        print()

    print("=" * 80)
    print("РЕЗУЛЬТАТ:")
    print(f"  Обновлено платежей: {updated_count}")
    print(f"  Пропущено платежей: {skipped_count}")

    if errors:
        print()
        print("ОШИБКИ:")
        for error in errors[:10]:  # Показываем первые 10 ошибок
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... и еще {len(errors) - 10} ошибок")

    print("=" * 80)

    if updated_count > 0:
        print()
        print("✓ Проблема исправлена!")
        print("  Теперь в отчетах по КВ должны отображаться корректные значения.")


if __name__ == "__main__":
    main()
