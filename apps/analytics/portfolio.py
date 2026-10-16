"""
Портфель для Аналитики 2.0: новый бизнес, окончания, продления
(docs/analytics-2.0-plan.md, §3.2).

На вход — выборки полисов из AnalyticsParams (разрезы, ОСАГО и исключение
полисов без участия брокера уже применены).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict

from django.db.models import Count, DecimalField, F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce

from apps.policies.models import PaymentSchedule, in_force_q

ZERO = Decimal("0")

# Полис с активным ДФА, заканчивающийся в ближайшие N дней, — сигнал сводки.
ENDING_SOON_DAYS = 60


def _money(field):
    return Coalesce(
        Sum(field), ZERO, output_field=DecimalField(max_digits=15, decimal_places=2)
    )


def new_business(policies: QuerySet, start: date, end: date) -> QuerySet:
    """Новый бизнес: полисы с датой начала в периоде."""
    return policies.filter(start_date__gte=start, start_date__lte=end)


def new_business_totals(policies: QuerySet, start: date, end: date) -> Dict[str, Any]:
    """Полисов, из них к старому ДФА; премия и КВ первого года."""
    selected = new_business(policies, start, end)
    counts = selected.aggregate(
        count=Count("id"), to_old_dfa=Count("id", filter=Q(renewal_to_old_dfa=True))
    )
    first_year = PaymentSchedule.objects.filter(
        policy__in=selected, year_number=1
    ).aggregate(premium=_money("amount"), commission=_money("kv_rub"))
    return {**counts, **first_year}


def dfa_active_on_end_q() -> Q:
    """ДФА активен на дату окончания полиса: не закрыт или закрыт позже."""
    return Q(dfa_active=True) | Q(dfa_deactivation_date__gt=F("end_date"))


def ending_soon(policies: QuerySet, today: date, days: int = ENDING_SOON_DAYS):
    """В силе сегодня, ДФА активен, окончание в ближайшие days дней."""
    return policies.filter(
        in_force_q(today),
        end_date__lte=today + timedelta(days=days),
        dfa_active=True,
    )
