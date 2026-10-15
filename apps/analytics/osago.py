"""
Аналитика ОСАГО — отдельная страница (основная аналитика идёт без ОСАГО).

Год — по дате начала полиса: полисы ОСАГО, заключённые в выбранном году.
Премия и КВ — по их единственному платежу.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce, ExtractMonth
from django.utils import timezone

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

TOP_CLIENTS = 20

_ZERO = Decimal("0")


def _money(field):
    return Coalesce(
        Sum(field), _ZERO, output_field=DecimalField(max_digits=15, decimal_places=2)
    )


def _breakdown(payments, label_field: str, id_field: str) -> List[Dict[str, Any]]:
    rows = (
        payments.values(label_field, id_field)
        .annotate(
            policies=Count("policy", distinct=True),
            premium=_money("amount"),
            kv=_money("kv_rub"),
        )
        .order_by("-premium", label_field)
    )
    return [
        {
            "id": row[id_field],
            "name": row[label_field] or "Не указано",
            "policies": row["policies"],
            "premium": row["premium"],
            "kv": row["kv"],
        }
        for row in rows
    ]


def available_years(today=None) -> List[int]:
    from apps.policies.models import Policy

    today = today or timezone.localdate()
    years = {d.year for d in Policy.objects.osago().dates("start_date", "year")}
    years.add(today.year)
    return sorted(years, reverse=True)


def build_osago_analytics(year: Optional[int] = None, today=None) -> Dict[str, Any]:
    from apps.policies.models import PaymentSchedule, Policy

    today = today or timezone.localdate()
    year = year or today.year

    policies = Policy.objects.osago().filter(start_date__year=year)
    payments = PaymentSchedule.objects.osago().filter(policy__start_date__year=year)

    totals = payments.aggregate(
        premium=_money("amount"),
        kv=_money("kv_rub"),
        paid=Count("id", filter=Q(paid_date__isnull=False)),
        approved=Count("id", filter=Q(insurer_date__isnull=False)),
    )
    totals["policies"] = policies.count()
    totals["in_force"] = Policy.objects.osago().in_force(today).count()
    totals["kv_percent"] = (
        totals["kv"] / totals["premium"] * Decimal("100")
        if totals["premium"]
        else _ZERO
    )

    month_rows = {
        row["month"]: row
        for row in payments.annotate(month=ExtractMonth("policy__start_date"))
        .values("month")
        .annotate(
            policies=Count("policy", distinct=True),
            premium=_money("amount"),
            kv=_money("kv_rub"),
        )
    }
    by_month = [
        {
            "month": number,
            "name": MONTH_NAMES[number - 1],
            "policies": month_rows.get(number, {}).get("policies", 0),
            "premium": month_rows.get(number, {}).get("premium", _ZERO),
            "kv": month_rows.get(number, {}).get("kv", _ZERO),
        }
        for number in range(1, 13)
    ]

    by_client = _breakdown(payments, "policy__client__client_name", "policy__client_id")

    return {
        "year": year,
        "years": available_years(today),
        "totals": totals,
        "by_month": by_month,
        "by_branch": _breakdown(
            payments, "policy__branch__branch_name", "policy__branch_id"
        ),
        "by_insurer": _breakdown(
            payments, "policy__insurer__insurer_name", "policy__insurer_id"
        ),
        "by_client": by_client[:TOP_CLIENTS],
        "clients_total": len(by_client),
    }
