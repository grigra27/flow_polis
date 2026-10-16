"""
Деньги брокера: единые определения для финансовой аналитики и временных рядов.

Решение владельца 2026-10-16: «заработано» — по дате согласования акта с СК
(insurer_date), как в ежемесячном отчёте по КВ. Отсюда:

- заработано — платежи с insurer_date в периоде;
- ждёт акта — клиент оплатил (paid_date), акт с СК ещё не согласован;
- ожидается по графику — неоплаченные платежи, которые ещё реально придут;
- просрочено — то же, но срок платежа уже прошёл.

«Реально придут» = не отменены: полис активен (расторгнутый полис без оплаты
денег не принесёт) и платёж не отсечён закрытием ДФА (dfa_deactivated_payments_q,
то же правило, что у очередных взносов).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Count, DecimalField, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, ExtractMonth, TruncMonth

from apps.policies.models import dfa_deactivated_payments_q

ZERO = Decimal("0")

MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
MONTH_SHORT = [name[:3] for name in MONTH_NAMES]


def _money(field):
    return Coalesce(
        Sum(field), ZERO, output_field=DecimalField(max_digits=15, decimal_places=2)
    )


def _totals(queryset: QuerySet) -> Dict[str, Any]:
    return queryset.aggregate(
        premium=_money("amount"), commission=_money("kv_rub"), count=Count("id")
    )


def cancelled_q() -> Q:
    """Платежи, которых уже не будет: не оплачены и полис неактивен или ДФА закрыт."""
    return Q(paid_date__isnull=True) & (
        Q(policy__policy_active=False) | dfa_deactivated_payments_q()
    )


def scheduled_payments(payments: QuerySet) -> QuerySet:
    """График без отменённых платежей (оплаченные остаются)."""
    return payments.exclude(cancelled_q())


def expected_payments(payments: QuerySet) -> QuerySet:
    """Неоплаченные платежи, которые ещё ожидаются."""
    return scheduled_payments(payments).filter(paid_date__isnull=True)


def earned_payments(payments: QuerySet, start: date, end: date) -> QuerySet:
    """Заработано за период: акт с СК согласован в [start, end]."""
    return payments.filter(insurer_date__gte=start, insurer_date__lte=end)


def awaiting_act_payments(payments: QuerySet) -> QuerySet:
    """Клиент оплатил, акт с СК ещё не согласован — ближайшие поступления КВ."""
    return payments.filter(paid_date__isnull=False, insurer_date__isnull=True)


def build_current_year_outlook(payments: QuerySet, today: date) -> Dict[str, Any]:
    """Год как мост: заработано + ждёт акта + ожидается по графику; просрочено — отдельно."""
    year = today.year
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)

    earned_qs = earned_payments(payments, year_start, today)
    expected_qs = expected_payments(payments)
    scheduled_qs = expected_qs.filter(due_date__gte=today, due_date__lte=year_end)
    overdue_qs = expected_qs.filter(due_date__lt=today)

    earned = _totals(earned_qs)
    awaiting = _totals(awaiting_act_payments(payments))
    scheduled = _totals(scheduled_qs)
    overdue = _totals(overdue_qs)

    def by_month(queryset, date_field):
        return {
            row["month"]: row
            for row in queryset.annotate(month=ExtractMonth(date_field))
            .values("month")
            .annotate(premium=_money("amount"), commission=_money("kv_rub"))
        }

    earned_by_month = by_month(earned_qs, "insurer_date")
    scheduled_by_month = by_month(scheduled_qs, "due_date")

    monthly_breakdown = []
    for month in range(1, 13):
        earned_row = earned_by_month.get(month, {})
        scheduled_row = scheduled_by_month.get(month, {})
        if month < today.month:
            mode = "actual"
        elif month == today.month:
            mode = "current"
        else:
            mode = "forecast"
        monthly_breakdown.append(
            {
                "month": month,
                "month_name": MONTH_NAMES[month - 1],
                "month_short": MONTH_SHORT[month - 1],
                "mode": mode,
                "earned_premium": earned_row.get("premium", ZERO),
                "earned_commission": earned_row.get("commission", ZERO),
                "scheduled_premium": scheduled_row.get("premium", ZERO),
                "scheduled_commission": scheduled_row.get("commission", ZERO),
            }
        )

    return {
        "year": year,
        "as_of": today,
        "current_month": today.month,
        "earned_premium": earned["premium"],
        "earned_commission": earned["commission"],
        "awaiting_act_premium": awaiting["premium"],
        "awaiting_act_commission": awaiting["commission"],
        "awaiting_act_count": awaiting["count"],
        "scheduled_premium": scheduled["premium"],
        "scheduled_commission": scheduled["commission"],
        "scheduled_count": scheduled["count"],
        "overdue_premium": overdue["premium"],
        "overdue_commission": overdue["commission"],
        "overdue_count": overdue["count"],
        "projected_full_year_premium": earned["premium"]
        + awaiting["premium"]
        + scheduled["premium"],
        "projected_full_year_commission": earned["commission"]
        + awaiting["commission"]
        + scheduled["commission"],
        "monthly_breakdown": monthly_breakdown,
    }


def build_monthly_forecast(
    payments: QuerySet, today: date, min_months: int = 12
) -> List[Dict[str, Any]]:
    """График по месяцам от текущего до последнего платежа (без отменённых).

    Только заключённые договоры: будущие пролонгации сюда не входят, поэтому
    дальние месяцы заведомо ниже реальных.
    """
    first_month = today.replace(day=1)
    rows = {
        row["month"]: row
        for row in scheduled_payments(payments)
        .filter(due_date__gte=first_month)
        .annotate(month=TruncMonth("due_date"))
        .values("month")
        .annotate(premium=_money("amount"), commission=_money("kv_rub"))
    }
    last = max(rows) if rows else first_month
    months_count = max(
        min_months,
        (last.year - first_month.year) * 12 + last.month - first_month.month + 1,
    )

    forecast = []
    year, month = first_month.year, first_month.month
    for _ in range(months_count):
        month_date = date(year, month, 1)
        row = rows.get(month_date, {})
        forecast.append(
            {
                "month": month_date,
                "forecasted_premium": row.get("premium", ZERO),
                "forecasted_commission": row.get("commission", ZERO),
                "actual_premium": None,
                "actual_commission": None,
            }
        )
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return forecast


def build_payment_status(payments: QuerySet, today: date) -> Dict[str, Any]:
    """Платёжный контур: оплачено / ожидается / просрочено (без отменённых)."""
    expected_qs = expected_payments(payments)
    paid = _totals(payments.filter(paid_date__isnull=False))
    pending = _totals(expected_qs.filter(due_date__gte=today))
    overdue = _totals(expected_qs.filter(due_date__lt=today))
    total_count = payments.count()
    return {
        "total_payments": total_count,
        "paid_payments": paid["count"],
        "pending_payments": pending["count"],
        "overdue_payments": overdue["count"],
        "paid_amount": paid["premium"],
        "pending_amount": pending["premium"],
        "overdue_amount": overdue["premium"],
        "payment_discipline_rate": (
            Decimal(paid["count"]) / Decimal(total_count) * 100 if total_count else ZERO
        ),
    }


def year_to_date_totals(
    payments: QuerySet, today: date, year: Optional[int] = None
) -> Dict[str, Decimal]:
    """Заработано за 1 января – тот же день года `year` (для сравнения год к году)."""
    year = year or today.year
    end_day = today.day
    if (today.month, today.day) == (2, 29):
        end_day = 28 if year % 4 else 29
    start, end = date(year, 1, 1), date(year, today.month, end_day)
    return _totals(earned_payments(payments, start, end))


def earned_monthly_series(payments: QuerySet, start: date, end: date):
    """Заработано по месяцам (по дате акта) — факт для временных рядов."""
    return [
        {
            "month": row["month"],
            "premium": row["premium"],
            "commission": row["commission"],
        }
        for row in earned_payments(payments, start, end)
        .annotate(month=TruncMonth("insurer_date"))
        .values("month")
        .annotate(premium=_money("amount"), commission=_money("kv_rub"))
        .order_by("month")
    ]
