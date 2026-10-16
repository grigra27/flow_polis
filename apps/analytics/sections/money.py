"""
Вкладка «Деньги»: сколько заработали, сколько придёт, где деньги застряли
и сколько потеряли (docs/analytics-2.0-plan.md, §4 B).

Период фильтра режет: заработано (по дате акта), план и ожидание (по дате
платежа), потери (по дате события). «Ждёт акта», «просрочено», прогноз на
12 месяцев и «обеспечено» — срез на сегодня, от периода не зависят.
"""

import calendar
from datetime import date, timedelta

from django.utils.dateparse import parse_date

from .. import money
from ..drilldown import PAYMENTS, metric

USES_PERIOD = True


# --- опции списков -------------------------------------------------------------


def month_range(opts):
    """month=YYYY-MM → (первый, последний день) или None."""
    value = opts.get("month") or ""
    start = parse_date(f"{value}-01") if len(value) == 7 else None
    if not start:
        return None
    return start, date(
        start.year, start.month, calendar.monthrange(start.year, start.month)[1]
    )


def narrow(start, end, opts):
    """Сужает период до месяца из opts (если он задан)."""
    found = month_range(opts)
    if found:
        return max(start, found[0]), min(end, found[1])
    return start, end


# --- величины ----------------------------------------------------------------


@metric("earned", "КВ заработано (акт с СК в периоде)", PAYMENTS)
def earned(params, opts):
    start, end = narrow(params.date_from, params.date_to, opts)
    return money.earned_payments(params.payments(), start, end)


@metric("plan", "План по графику (без отменённых)", PAYMENTS)
def plan(params, opts):
    start, end = narrow(params.date_from, params.date_to, opts)
    return money.scheduled_payments(params.payments()).filter(
        due_date__gte=start, due_date__lte=end
    )


@metric(
    "expected",
    "Ожидается по графику до конца периода",
    PAYMENTS,
    note="Не оплачены и не отменены, дата платежа — с сегодняшнего дня до конца периода.",
)
def expected(params, opts):
    start, end = narrow(max(params.date_from, params.today), params.date_to, opts)
    return money.expected_payments(params.payments()).filter(
        due_date__gte=start, due_date__lte=end
    )


@metric(
    "awaiting_act",
    "Ждёт акта СК (клиент оплатил)",
    PAYMENTS,
    note="Срез на сегодня, от периода не зависит.",
)
def awaiting_act(params, opts):
    queryset = money.awaiting_act_payments(params.payments())
    age = opts.get("age")
    if age == "60+":
        return queryset.filter(paid_date__lt=params.today - timedelta(days=60))
    bucket = money.age_bucket_q(age or "", params.today)
    return queryset.filter(bucket) if bucket is not None else queryset


@metric(
    "overdue",
    "Просрочено (не оплачено, срок прошёл)",
    PAYMENTS,
    note="Срез на сегодня, от периода не зависит. Отменённые платежи сюда не входят.",
)
def overdue(params, opts):
    return money.expected_payments(params.payments()).filter(due_date__lt=params.today)


@metric(
    "lost",
    "Потеряно (отменённые платежи)",
    PAYMENTS,
    note="Не оплачены и уже не будут: ДФА закрыт или полис расторгнут. "
    "Период — по дате события.",
)
def lost(params, opts):
    rows = money.lost_rows(params.payments())
    if opts.get("undated") == "1":
        rows = [row for row in rows if row["loss_date"] is None]
    elif opts.get("all") != "1":
        start, end = narrow(params.date_from, params.date_to, opts)
        rows = money.lost_in_period(rows, start, end)
    reason = opts.get("reason")
    if reason:
        rows = [row for row in rows if row["reason"] == reason]
    return params.payments().filter(id__in=[row["id"] for row in rows])


@metric(
    "forecast",
    "Прогноз: ожидается по графику",
    PAYMENTS,
    note="Неоплаченные и неотменённые платежи с сегодняшнего дня. Пролонгации не учтены.",
)
def forecast(params, opts):
    queryset = money.expected_payments(params.payments()).filter(
        due_date__gte=params.today
    )
    found = month_range(opts)
    if found:
        queryset = queryset.filter(due_date__gte=found[0], due_date__lte=found[1])
    return queryset


@metric(
    "secured",
    "Обеспечено на будущие годы",
    PAYMENTS,
    note="Ожидается по графику действующих договоров после текущего года.",
)
def secured(params, opts):
    queryset = money.expected_payments(params.payments()).filter(
        due_date__gt=date(params.today.year, 12, 31)
    )
    year = opts.get("year")
    if year and str(year).isdigit():
        queryset = queryset.filter(due_date__year=int(year))
    return queryset


@metric(
    "non_broker_payments",
    "Платежи полисов без участия брокера",
    PAYMENTS,
    note="Исключены из всех показателей раздела.",
)
def non_broker_payments(params, opts):
    start, end = narrow(params.date_from, params.date_to, opts)
    return params.non_broker_payments().filter(due_date__gte=start, due_date__lte=end)


# --- вкладка -------------------------------------------------------------------


def _group_losses(rows, field, label_field):
    groups = {}
    for row in rows:
        key = row[field]
        group = groups.setdefault(
            key, {"id": key, "name": row[label_field] or "—", "rows": []}
        )
        group["rows"].append(row)
    result = []
    for group in groups.values():
        totals = money.sum_rows(group.pop("rows"))
        result.append({**group, **totals})
    result.sort(key=lambda r: -r["commission"])
    return result


def build(params, query=None):
    payments = params.payments()
    today = params.today
    start, end = params.date_from, params.date_to

    earned_totals = money._totals(money.earned_payments(payments, start, end))
    plan_totals = money._totals(
        money.scheduled_payments(payments).filter(
            due_date__gte=start, due_date__lte=end
        )
    )
    expected_totals = money._totals(expected(params, {}))
    awaiting_totals = money._totals(money.awaiting_act_payments(payments))
    overdue_totals = money._totals(overdue(params, {}))

    loss_rows = money.lost_rows(
        payments,
        "policy__branch_id",
        "policy__branch__branch_name",
        "policy__insurer_id",
        "policy__insurer__insurer_name",
    )
    period_losses = money.lost_in_period(loss_rows, start, end)
    undated_losses = [row for row in loss_rows if row["loss_date"] is None]

    monthly = money.monthly_earned_vs_plan(payments, start, end)
    loss_by_month = {}
    for row in period_losses:
        month = row["loss_date"].replace(day=1)
        loss_by_month.setdefault(month, {key: money.ZERO for key in money.LOSS_REASONS})
        loss_by_month[month][row["reason"]] += row["kv_rub"]

    reasons = []
    for key, label in money.LOSS_REASONS.items():
        totals = money.sum_rows([row for row in period_losses if row["reason"] == key])
        reasons.append({"key": key, "label": label, **totals})

    non_broker = money._totals(non_broker_payments(params, {}))
    forecast_rows = [
        {**row, "month_code": f"{row['month']:%Y-%m}"}
        for row in money.expected_by_month(payments, today)
    ]

    return {
        "kpi": {
            "earned": earned_totals,
            "plan": plan_totals,
            "expected": expected_totals,
            "awaiting": awaiting_totals,
            "overdue": overdue_totals,
            "lost": money.sum_rows(period_losses),
            "lost_undated": money.sum_rows(undated_losses),
            "plan_completion": (
                earned_totals["commission"] / plan_totals["commission"] * 100
                if plan_totals["commission"]
                else None
            ),
        },
        "monthly": [
            {
                **row,
                "month_code": f"{row['month']:%Y-%m}",
                "lost_commission": sum(
                    loss_by_month.get(row["month"], {}).values(), money.ZERO
                ),
            }
            for row in monthly
        ],
        "chart": {
            "labels": [row["label"] for row in monthly],
            "earned": [float(row["earned_commission"]) for row in monthly],
            "plan": [float(row["plan_commission"]) for row in monthly],
        },
        "debt": money.awaiting_act_by_insurer(payments, today),
        "age_buckets": [
            {"key": key, "label": label} for key, label, _, _ in money.AGE_BUCKETS
        ],
        "loss_reasons": reasons,
        "loss_by_branch": _group_losses(
            period_losses, "policy__branch_id", "policy__branch__branch_name"
        ),
        "loss_by_insurer": _group_losses(
            period_losses, "policy__insurer_id", "policy__insurer__insurer_name"
        ),
        "forecast": forecast_rows,
        "forecast_chart": {
            "labels": [row["label"] for row in forecast_rows],
            "values": [float(row["commission"]) for row in forecast_rows],
        },
        "secured": money.secured_by_year(payments, today),
        "non_broker": non_broker,
    }
