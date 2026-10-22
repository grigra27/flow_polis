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

from apps.policies.models import PaymentSchedule, in_force_q, prolongable_q

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


# --- кварталы -------------------------------------------------------------------

QUARTER_NAMES = ["I", "II", "III", "IV"]


def quarter_start(value: date) -> date:
    return date(value.year, (value.month - 1) // 3 * 3 + 1, 1)


def quarter_end(start: date) -> date:
    month = start.month + 3
    year = start.year + (month > 12)
    month = month - 12 if month > 12 else month
    return date(year, month, 1) - timedelta(days=1)


def quarter_code(start: date) -> str:
    return f"{start.year}Q{(start.month - 1) // 3 + 1}"


def quarter_label(start: date) -> str:
    return f"{QUARTER_NAMES[(start.month - 1) // 3]} кв. {start.year}"


def parse_quarter(code: str):
    """'2026Q3' → (начало, конец) или None."""
    try:
        year, number = code.upper().split("Q")
        start = date(int(year), (int(number) - 1) * 3 + 1, 1)
    except (AttributeError, ValueError):
        return None
    return start, quarter_end(start)


def quarters_between(start: date, end: date):
    current = quarter_start(start)
    result = []
    while current <= end:
        result.append(current)
        current = quarter_end(current) + timedelta(days=1)
    return result


# --- окончания и продления --------------------------------------------------------

# Новый полис по тому же ДФА с датой начала в пределах ±N дней от окончания
# старого считается продлением (решение владельца 2026-10-16: продление — только
# в рамках того же ДФА, VIN не используется).
RENEWAL_WINDOW_DAYS = 45

RENEWED = "renewed"
SWITCHED = "switched"
NOT_RENEWED = "not_renewed"


def expiring(policies: QuerySet, start: date, end: date) -> QuerySet:
    """Заканчиваются в периоде естественно: не расторгнуты и не закрыты флагом."""
    return policies.filter(
        end_date__gte=start,
        end_date__lte=end,
        termination_date__isnull=True,
        policy_active=True,
    )


def renewal_due(policies: QuerySet, start: date, end: date) -> QuerySet:
    """Требовали продления: закончились в периоде при активном на окончание ДФА.

    ОСАГО не продлевается в этом смысле, грузы не продлевают никогда —
    исключены всегда.
    """
    return (
        expiring(policies, start, end)
        .filter(dfa_active_on_end_q())
        .exclude(insurance_type__is_osago=True)
        .filter(prolongable_q())
    )


def _dfa_key(value: str) -> str:
    return " ".join((value or "").split()).upper()


def renewal_statuses(due: QuerySet) -> Dict[int, Dict[str, Any]]:
    """Статус продления каждого полиса из due: {id: {status, successor_id}}.

    Преемник ищется среди всех полисов (не ОСАГО) без учёта фильтров раздела:
    при смене СК или филиала новый полис может не попасть в выборку.
    """
    from apps.policies.models import Policy

    due_rows = list(due.values("id", "dfa_number", "end_date", "insurer_id"))
    candidates: Dict[str, list] = {}
    if due_rows:
        # Полисов немного (~1–2 тыс.), а номер ДФА бывает записан с разными
        # пробелами/регистром — сравниваем нормализованный ключ в Python.
        for row in Policy.objects.exclude(insurance_type__is_osago=True).values(
            "id", "dfa_number", "start_date", "insurer_id"
        ):
            key = _dfa_key(row["dfa_number"])
            if key:
                candidates.setdefault(key, []).append(row)

    window = timedelta(days=RENEWAL_WINDOW_DAYS)
    result = {}
    for row in due_rows:
        matches = [
            c
            for c in candidates.get(_dfa_key(row["dfa_number"]), [])
            if c["id"] != row["id"] and abs(c["start_date"] - row["end_date"]) <= window
        ]
        if not matches:
            result[row["id"]] = {"status": NOT_RENEWED, "successor_id": None}
            continue
        same_insurer = [c for c in matches if c["insurer_id"] == row["insurer_id"]]
        best = min(
            same_insurer or matches,
            key=lambda c: abs(c["start_date"] - row["end_date"]),
        )
        result[row["id"]] = {
            "status": RENEWED if same_insurer else SWITCHED,
            "successor_id": best["id"],
        }
    return result


def retention_by_quarter(policies: QuerySet, start: date, end: date):
    """По кварталам: требовали продления → продлены (из них к другой СК) → нет."""
    rows = []
    for q_start in quarters_between(start, end):
        q_end = min(quarter_end(q_start), end)
        statuses = renewal_statuses(renewal_due(policies, q_start, q_end))
        due = len(statuses)
        renewed = sum(1 for s in statuses.values() if s["status"] == RENEWED)
        switched = sum(1 for s in statuses.values() if s["status"] == SWITCHED)
        rows.append(
            {
                "start": q_start,
                "end": q_end,
                "code": quarter_code(q_start),
                "label": quarter_label(q_start),
                "due": due,
                "renewed": renewed + switched,
                "switched": switched,
                "not_renewed": due - renewed - switched,
                "rate": (renewed + switched) / due * 100 if due else None,
            }
        )
    return rows


# --- отток ---------------------------------------------------------------------


def early_buyouts(policies: QuerySet, start: date, end: date) -> QuerySet:
    """ДФА закрыт в периоде раньше окончания полиса больше чем на 30 дней."""
    from . import money

    ids = [
        row["id"]
        for row in policies.filter(
            dfa_active=False,
            dfa_deactivation_date__gte=start,
            dfa_deactivation_date__lte=end,
            termination_date__isnull=True,
        ).values("id", "dfa_deactivation_date", "end_date")
        if (row["end_date"] - row["dfa_deactivation_date"]).days
        > money.EARLY_BUYOUT_DAYS
    ]
    return policies.filter(id__in=ids)


def terminations(policies: QuerySet, start: date, end: date) -> QuerySet:
    return policies.filter(termination_date__gte=start, termination_date__lte=end)
