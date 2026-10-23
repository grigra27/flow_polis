"""
Деньги брокера: единые определения для аналитики, главной и отчётов.

Решение владельца 2026-10-16: «заработано» — по дате согласования акта с СК
(insurer_date), как в ежемесячном отчёте по КВ. Отсюда:

- заработано — платежи с insurer_date в периоде;
- ждёт акта — клиент оплатил (paid_date), акт с СК ещё не согласован;
- ожидается по графику — неоплаченные платежи, которые ещё реально придут;
- просрочено — то же, но срок платежа уже прошёл.

«Реально придут» = не отменены: полис активен (расторгнутый полис без оплаты
денег не принесёт) и платёж не отсечён закрытием ДФА (dfa_deactivated_payments_q,
то же правило, что у очередных взносов). ДФА, закрытый без даты закрытия,
отсекает все неоплаченные платежи полиса: когда именно он закрыт, неизвестно,
но этих денег уже не будет.

Аналитика 2.0 (docs/analytics-2.0-plan.md, §3.1) добавляет:

- потеряно — отменённые платежи с причиной (расторжение, досрочный выкуп,
  плановое закрытие ДФА, не определено) и датой события;
- долг СК по актам — «ждёт акта» по корзинам возраста;
- обеспечено на будущие годы — ожидается с due_date после текущего года.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Count, DecimalField, Min, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear, TruncMonth

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


def dfa_closed_without_date_q() -> Q:
    """ДФА закрыт, но дата закрытия не указана."""
    return Q(policy__dfa_active=False, policy__dfa_deactivation_date__isnull=True)


def cancelled_q() -> Q:
    """Платежи, которых уже не будет: не оплачены и полис неактивен или ДФА закрыт."""
    return Q(paid_date__isnull=True) & (
        Q(policy__policy_active=False)
        | dfa_deactivated_payments_q()
        | dfa_closed_without_date_q()
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


# --- Аналитика 2.0: граница надёжной истории ----------------------------------

# База заполнялась в конце 2025 года задним числом: до июля 2025 в ней лишь
# часть платежей и актов (3–26 актов в месяц против 50–150 позже). Сравнения
# с периодами раньше этой даты завышают рост — их не показываем.
HISTORY_RELIABLE_FROM = date(2025, 7, 1)


def history_is_reliable(start: date) -> bool:
    return start >= HISTORY_RELIABLE_FROM


# --- Аналитика 2.0: потери ---------------------------------------------------

# Досрочный выкуп: ДФА закрыт раньше окончания полиса больше чем на столько дней
# (решение владельца 2026-10-16).
EARLY_BUYOUT_DAYS = 30

LOSS_TERMINATION = "termination"
LOSS_EARLY_BUYOUT = "early_buyout"
LOSS_PLANNED_CLOSE = "planned_close"
LOSS_UNKNOWN = "unknown"

LOSS_REASONS = {
    LOSS_EARLY_BUYOUT: "Досрочный выкуп",
    LOSS_PLANNED_CLOSE: "Плановое закрытие ДФА",
    LOSS_TERMINATION: "Расторжение полиса",
    LOSS_UNKNOWN: "Не определено",
}

_LOSS_FIELDS = (
    "id",
    "amount",
    "kv_rub",
    "policy__termination_date",
    "policy__dfa_active",
    "policy__dfa_deactivation_date",
    "policy__end_date",
)


def lost_payments(payments: QuerySet) -> QuerySet:
    """Потеряно: неоплаченные платежи, которых уже не будет."""
    return payments.filter(cancelled_q())


def classify_loss(row: Dict[str, Any]):
    """(причина, дата события) потерянного платежа по полям полиса.

    Расторжение важнее закрытия ДФА. Дата неизвестна, если полис закрыт
    флагом без даты расторжения или ДФА закрыт без даты.
    """
    if row["policy__termination_date"]:
        return LOSS_TERMINATION, row["policy__termination_date"]
    closed_on = row["policy__dfa_deactivation_date"]
    if not row["policy__dfa_active"] and closed_on:
        days_before_end = (row["policy__end_date"] - closed_on).days
        if days_before_end > EARLY_BUYOUT_DAYS:
            return LOSS_EARLY_BUYOUT, closed_on
        return LOSS_PLANNED_CLOSE, closed_on
    return LOSS_UNKNOWN, None


def lost_rows(payments: QuerySet, *extra_fields: str) -> List[Dict[str, Any]]:
    """Потерянные платежи с причиной (reason) и датой события (loss_date).

    Классификация в Python: потерь сотни, а правило с датами проще и точнее
    проверить без SQL-арифметики дат, которая различается в SQLite и PostgreSQL.
    """
    rows = []
    for row in lost_payments(payments).values(*_LOSS_FIELDS, *extra_fields):
        row["reason"], row["loss_date"] = classify_loss(row)
        rows.append(row)
    return rows


def lost_in_period(rows, start: date, end: date, include_undated: bool = False):
    return [
        row
        for row in rows
        if (row["loss_date"] and start <= row["loss_date"] <= end)
        or (include_undated and row["loss_date"] is None)
    ]


def sum_rows(rows) -> Dict[str, Any]:
    return {
        "premium": sum((row["amount"] for row in rows), ZERO),
        "commission": sum((row["kv_rub"] for row in rows), ZERO),
        "count": len(rows),
    }


# --- Аналитика 2.0: долг СК по актам ------------------------------------------

# Корзины возраста «ждёт акта»: (ключ, подпись, от дней, до дней включительно).
AGE_BUCKETS = [
    ("0-30", "0–30 дн.", 0, 30),
    ("31-60", "31–60 дн.", 31, 60),
    ("61-90", "61–90 дн.", 61, 90),
    ("90+", "90+ дн.", 91, None),
]


def age_bucket_q(key: str, today: date) -> Optional[Q]:
    """Q по возрасту ожидания акта (сегодня − дата оплаты) для корзины."""
    for bucket_key, _, low, high in AGE_BUCKETS:
        if bucket_key == key:
            q = Q(paid_date__lte=today - timedelta(days=low))
            if high is not None:
                q &= Q(paid_date__gte=today - timedelta(days=high))
            return q
    return None


def awaiting_act_by_insurer(payments: QuerySet, today: date) -> List[Dict[str, Any]]:
    """Ждёт акта по страховщикам с разбивкой по возрасту. Сортировка: 90+ ↓, сумма ↓."""
    awaiting = awaiting_act_payments(payments)
    aggregates = {
        "commission": _money("kv_rub"),
        "count": Count("id"),
        "oldest": Min("paid_date"),
    }
    for key, _, _, _ in AGE_BUCKETS:
        aggregates[f"b_{key}"] = Coalesce(
            Sum("kv_rub", filter=age_bucket_q(key, today)),
            ZERO,
            output_field=DecimalField(max_digits=15, decimal_places=2),
        )
    rows = []
    for row in (
        awaiting.values("policy__insurer_id", "policy__insurer__insurer_name")
        .annotate(**aggregates)
        .order_by()
    ):
        rows.append(
            {
                "insurer_id": row["policy__insurer_id"],
                "insurer": row["policy__insurer__insurer_name"],
                "commission": row["commission"],
                "count": row["count"],
                "oldest": row["oldest"],
                "oldest_days": (today - row["oldest"]).days if row["oldest"] else None,
                "buckets": [
                    {"key": key, "commission": row[f"b_{key}"]}
                    for key, _, _, _ in AGE_BUCKETS
                ],
                "over_90": row["b_90+"],
            }
        )
    rows.sort(key=lambda r: (-r["over_90"], -r["commission"]))
    return rows


# --- Аналитика 2.0: план, ожидание, обеспечено --------------------------------


def month_starts(start: date, end: date) -> List[date]:
    months = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return months


def monthly_earned_vs_plan(
    payments: QuerySet, start: date, end: date
) -> List[Dict[str, Any]]:
    """По месяцам периода: заработано по актам и план по графику (без отменённых)."""

    def grouped(queryset, date_field):
        return {
            row["month"]: row
            for row in queryset.annotate(month=TruncMonth(date_field))
            .values("month")
            .annotate(premium=_money("amount"), commission=_money("kv_rub"))
            .order_by()
        }

    earned = grouped(earned_payments(payments, start, end), "insurer_date")
    plan = grouped(
        scheduled_payments(payments).filter(due_date__gte=start, due_date__lte=end),
        "due_date",
    )
    rows = []
    for month in month_starts(start, end):
        e, p = earned.get(month, {}), plan.get(month, {})
        rows.append(
            {
                "month": month,
                "label": f"{MONTH_SHORT[month.month - 1]} {month:%y}",
                "earned_commission": e.get("commission", ZERO),
                "earned_premium": e.get("premium", ZERO),
                "plan_commission": p.get("commission", ZERO),
                "plan_premium": p.get("premium", ZERO),
            }
        )
    return rows


def expected_by_month(
    payments: QuerySet, today: date, months: int = 12
) -> List[Dict[str, Any]]:
    """Прогноз: ожидается по графику помесячно с текущего месяца (без просрочки)."""
    month_list = [today.replace(day=1)]
    for _ in range(months):
        month_list.append((month_list[-1] + timedelta(days=32)).replace(day=1))
    end = month_list.pop() - timedelta(days=1)
    grouped = {
        row["month"]: row
        for row in expected_payments(payments)
        .filter(due_date__gte=today, due_date__lte=end)
        .annotate(month=TruncMonth("due_date"))
        .values("month")
        .annotate(
            premium=_money("amount"), commission=_money("kv_rub"), count=Count("id")
        )
        .order_by()
    }
    return [
        {
            "month": month,
            "label": f"{MONTH_SHORT[month.month - 1]} {month:%y}",
            "commission": grouped.get(month, {}).get("commission", ZERO),
            "premium": grouped.get(month, {}).get("premium", ZERO),
            "count": grouped.get(month, {}).get("count", 0),
        }
        for month in month_list
    ]


def secured_by_year(payments: QuerySet, today: date) -> List[Dict[str, Any]]:
    """Обеспечено на будущие годы: ожидается по графику после текущего года."""
    return [
        {
            "year": row["year"],
            "commission": row["commission"],
            "premium": row["premium"],
            "count": row["count"],
        }
        for row in expected_payments(payments)
        .filter(due_date__gt=date(today.year, 12, 31))
        .annotate(year=ExtractYear("due_date"))
        .values("year")
        .annotate(
            premium=_money("amount"), commission=_money("kv_rub"), count=Count("id")
        )
        .order_by("year")
    ]
