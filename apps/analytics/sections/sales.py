"""
Вкладка «Продажи»: сколько нового бизнеса приводим и откуда
(docs/analytics-2.0-plan.md, §4 C).

Новый бизнес — полисы с датой начала в периоде; премия и КВ — по платежам
первого года. «К старому ДФА» — новый полис к существующему договору лизинга
(флаг renewal_to_old_dfa), показывается отдельной колонкой.
"""

from datetime import timedelta

from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth

from apps.policies.models import PaymentSchedule

from .. import money, portfolio

USES_PERIOD = True

GROUPINGS = {
    "branch": ("branch_id", "branch__branch_name", "Филиал"),
    "manager": ("leasing_manager_id", "leasing_manager__name", "Менеджер лизинга"),
    "insurer": ("insurer_id", "insurer__insurer_name", "Страховщик"),
    "type": ("insurance_type_id", "insurance_type__name", "Вид страхования"),
}
DEFAULT_GROUPING = "branch"
SHARE_TOP_INSURERS = 8


def _money(field):
    return Coalesce(
        Sum(field),
        money.ZERO,
        output_field=DecimalField(max_digits=15, decimal_places=2),
    )


def _first_year(policies, group_field):
    """{значение group_field полиса: {premium, commission}} по платежам 1-го года."""
    return {
        row["key"]: row
        for row in PaymentSchedule.objects.filter(policy__in=policies, year_number=1)
        .values(key=F(group_field))
        .annotate(premium=_money("amount"), commission=_money("kv_rub"))
        .order_by()
    }


def _monthly(selected, params):
    counts = {
        row["month"]: row
        for row in selected.annotate(month=TruncMonth("start_date"))
        .values("month")
        .annotate(
            count=Count("id"), to_old_dfa=Count("id", filter=Q(renewal_to_old_dfa=True))
        )
        .order_by()
    }
    first_year = {
        row["month"]: row
        for row in PaymentSchedule.objects.filter(policy__in=selected, year_number=1)
        .annotate(month=TruncMonth("policy__start_date"))
        .values("month")
        .annotate(premium=_money("amount"), commission=_money("kv_rub"))
        .order_by()
    }
    rows = []
    for month in money.month_starts(params.date_from, params.date_to):
        c, f = counts.get(month, {}), first_year.get(month, {})
        month_end = (month.replace(day=28) + timedelta(days=4)).replace(
            day=1
        ) - timedelta(days=1)
        rows.append(
            {
                "month": month,
                "date_from": max(month, params.date_from),
                "date_to": min(month_end, params.date_to),
                "label": f"{money.MONTH_SHORT[month.month - 1]} {month:%y}",
                "count": c.get("count", 0),
                "to_old_dfa": c.get("to_old_dfa", 0),
                "premium": f.get("premium", money.ZERO),
                "commission": f.get("commission", money.ZERO),
            }
        )
    return rows


def _grouped(selected, grouping):
    id_field, label_field, _ = GROUPINGS[grouping]
    first_year = _first_year(selected, f"policy__{id_field}")
    total_kv = sum((row["commission"] for row in first_year.values()), money.ZERO)
    rows = []
    for row in (
        selected.values(id_field, label_field)
        .annotate(
            count=Count("id"), to_old_dfa=Count("id", filter=Q(renewal_to_old_dfa=True))
        )
        .order_by()
    ):
        fy = first_year.get(row[id_field], {})
        premium = fy.get("premium", money.ZERO)
        commission = fy.get("commission", money.ZERO)
        rows.append(
            {
                "id": row[id_field],
                "name": row[label_field] or "Не указан",
                "count": row["count"],
                "to_old_dfa": row["to_old_dfa"],
                "premium": premium,
                "commission": commission,
                "avg_premium": premium / row["count"] if row["count"] else money.ZERO,
                "share": commission / total_kv * 100 if total_kv else None,
            }
        )
    rows.sort(key=lambda r: (-r["commission"], -r["count"]))
    return rows


def _insurer_share(selected, params):
    """Доля СК в числе новых полисов по кварталам периода."""
    quarters = portfolio.quarters_between(params.date_from, params.date_to)
    counts = {}
    totals = {}
    names = {}
    for insurer_id, name, start in selected.values_list(
        "insurer_id", "insurer__insurer_name", "start_date"
    ):
        q = portfolio.quarter_start(start)
        counts[(insurer_id, q)] = counts.get((insurer_id, q), 0) + 1
        totals[insurer_id] = totals.get(insurer_id, 0) + 1
        names[insurer_id] = name
    top = sorted(totals, key=lambda pk: -totals[pk])[:SHARE_TOP_INSURERS]
    quarter_totals = {
        q: sum(n for (_, qq), n in counts.items() if qq == q) for q in quarters
    }

    def share(pks, q):
        n = sum(counts.get((pk, q), 0) for pk in pks)
        return n / quarter_totals[q] * 100 if quarter_totals[q] else None

    others = [pk for pk in totals if pk not in top]
    rows = [
        {"id": pk, "name": names[pk], "shares": [share([pk], q) for q in quarters]}
        for pk in top
    ]
    if others:
        rows.append(
            {
                "id": None,
                "name": "Прочие",
                "shares": [share(others, q) for q in quarters],
            }
        )
    return {
        "quarters": [
            {"label": portfolio.quarter_label(q), "total": quarter_totals[q]}
            for q in quarters
        ],
        "rows": rows,
    }


def build(params, query=None):
    query = query or {}
    grouping = query.get("by") if query.get("by") in GROUPINGS else DEFAULT_GROUPING
    selected = portfolio.new_business(
        params.policies(), params.date_from, params.date_to
    )
    monthly = _monthly(selected, params)
    return {
        "totals": portfolio.new_business_totals(
            params.policies(), params.date_from, params.date_to
        ),
        "monthly": monthly,
        "chart": {
            "labels": [row["label"] for row in monthly],
            "count": [row["count"] for row in monthly],
            "commission": [float(row["commission"]) for row in monthly],
        },
        "grouping": grouping,
        "groupings": [
            {"key": key, "title": title} for key, (_, _, title) in GROUPINGS.items()
        ],
        "grouping_title": GROUPINGS[grouping][2],
        "grouped": _grouped(selected, grouping),
        "insurer_share": _insurer_share(selected, params),
    }
