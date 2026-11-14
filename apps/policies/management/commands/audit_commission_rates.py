"""Отчёт о неоднозначных старых связях. Команда не изменяет данные."""
import json

from django.core.management.base import BaseCommand
from django.db.models import F, Q

from apps.policies.models import Policy, PaymentSchedule


class Command(BaseCommand):
    help = "Проверить сохранённые базовые ставки без пересчёта и изменения данных"

    def handle(self, *args, **options):
        mismatched = PaymentSchedule.objects.filter(
            commission_rate__isnull=False
        ).exclude(
            commission_rate__insurer_id=F("policy__insurer_id"),
            commission_rate__insurance_type_id=F("policy__insurance_type_id"),
        )
        policies = Policy.objects.filter(
            Q(commission_rate_origin="review")
            | (
                Q(commission_rate__isnull=False)
                & ~Q(
                    commission_rate__insurer_id=F("insurer_id"),
                    commission_rate__insurance_type_id=F("insurance_type_id"),
                )
            )
        )
        self.stdout.write(
            json.dumps(
                {
                    "policies_requiring_review": list(
                        policies.order_by("pk").values_list("pk", flat=True)
                    ),
                    "payments_with_mismatched_rate": list(
                        mismatched.order_by("pk").values_list("pk", flat=True)
                    ),
                    "payments_without_rate": PaymentSchedule.objects.filter(
                        commission_rate__isnull=True
                    ).count(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
