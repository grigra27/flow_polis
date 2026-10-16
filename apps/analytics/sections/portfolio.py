"""
Вкладка «Портфель и удержание»: что в силе, что заканчивается и сколько
удерживаем (docs/analytics-2.0-plan.md, §4 D).

- срез «в силе» — на дату среза (as_of), по умолчанию сегодня;
- календарь окончаний — 12 месяцев от текущего;
- удержание и отток — по кварталам периода фильтра (не позже сегодня).
"""

from datetime import date, timedelta

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce

from apps.policies.models import PaymentSchedule, in_force_q

from .. import money, portfolio
from ..drilldown import POLICIES, metric
from .money import month_range

USES_PERIOD = True
USES_AS_OF = True

SNAPSHOT_HORIZON_DAYS = 365
CALENDAR_MONTHS = 12

DIMENSIONS = [
    ("insurance_type", "insurance_type__name", "type", "Вид страхования"),
    ("branch", "branch__branch_name", "branch", "Филиал"),
    ("insurer", "insurer__insurer_name", "insurer", "Страховщик"),
]


def _quarter(params, opts):
    """Квартал из opts или период фильтра, обрезанный сегодняшним днём."""
    found = portfolio.parse_quarter(opts.get("quarter") or "")
    start, end = found or (params.date_from, params.date_to)
    return start, min(end, params.today)


# --- величины -----------------------------------------------------------------


@metric("in_force_at", "Полисы в силе на дату среза", POLICIES)
def in_force_at(params, opts):
    return params.policies().filter(in_force_q(params.as_of))


@metric(
    "expiring",
    "Заканчиваются по сроку",
    POLICIES,
    note="Не расторгнуты. «Нужен новый полис» — ДФА открыт; «уходят» — ДФА закрыт.",
)
def expiring(params, opts):
    found = month_range(opts)
    if found:
        start, end = found
    else:
        start = params.today.replace(day=1)
        end = _calendar_end(start)
    queryset = portfolio.expiring(params.policies(), start, end)
    dfa = opts.get("dfa")
    if dfa == "open":
        queryset = queryset.filter(portfolio.dfa_active_on_end_q())
    elif dfa == "closed":
        queryset = queryset.exclude(portfolio.dfa_active_on_end_q())
    return queryset


@metric(
    "renewal_due",
    "Требовали продления (ДФА открыт на дату окончания)",
    POLICIES,
    note="Продлён — есть новый полис по тому же ДФА с началом в пределах ±45 дней "
    "от окончания. Расчёт приближённый: один ДФА может включать несколько объектов.",
)
def renewal_due(params, opts):
    start, end = _quarter(params, opts)
    due = portfolio.renewal_due(params.policies(), start, end)
    status = opts.get("status")
    if not status:
        return due
    statuses = portfolio.renewal_statuses(due)
    wanted = {
        "renewed": {portfolio.RENEWED, portfolio.SWITCHED},
        "switched": {portfolio.SWITCHED},
        "not_renewed": {portfolio.NOT_RENEWED},
    }.get(status, set())
    return due.filter(
        id__in=[pk for pk, s in statuses.items() if s["status"] in wanted]
    )


@metric(
    "churn",
    "Отток: досрочный выкуп и расторжение",
    POLICIES,
    note="Досрочный выкуп — ДФА закрыт раньше окончания полиса более чем на 30 дней.",
)
def churn(params, opts):
    start, end = _quarter(params, opts)
    reason = opts.get("reason")
    policies = params.policies()
    if reason == money.LOSS_EARLY_BUYOUT:
        return portfolio.early_buyouts(policies, start, end)
    if reason == money.LOSS_TERMINATION:
        return portfolio.terminations(policies, start, end)
    return portfolio.early_buyouts(policies, start, end) | portfolio.terminations(
        policies, start, end
    )


# --- вкладка ---------------------------------------------------------------------


def _calendar_end(start):
    month = start
    for _ in range(CALENDAR_MONTHS):
        month = (month + timedelta(days=32)).replace(day=1)
    return month - timedelta(days=1)


def _money(field):
    return Coalesce(
        Sum(field),
        money.ZERO,
        output_field=DecimalField(max_digits=15, decimal_places=2),
    )


def _snapshot(params):
    as_of = params.as_of
    in_force = params.policies().filter(in_force_q(as_of))
    horizon = PaymentSchedule.objects.filter(policy__in=in_force).filter(
        due_date__gte=as_of, due_date__lt=as_of + timedelta(days=SNAPSHOT_HORIZON_DAYS)
    )
    horizon = money.scheduled_payments(horizon)
    total = horizon.aggregate(commission=_money("kv_rub"), premium=_money("amount"))

    breakdowns = []
    for key, label_field, filter_name, title in DIMENSIONS:
        counts = {
            row[f"{key}_id"]: row
            for row in in_force.values(f"{key}_id", label_field)
            .annotate(count=Count("id"))
            .order_by()
        }
        kv = {
            row[f"policy__{key}_id"]: row["commission"]
            for row in horizon.values(f"policy__{key}_id")
            .annotate(commission=_money("kv_rub"))
            .order_by()
        }
        rows = [
            {
                "id": pk,
                "name": row[label_field],
                "count": row["count"],
                "commission": kv.get(pk, money.ZERO),
                "share": (
                    kv.get(pk, money.ZERO) / total["commission"] * 100
                    if total["commission"]
                    else None
                ),
            }
            for pk, row in counts.items()
        ]
        rows.sort(key=lambda r: (-r["commission"], -r["count"]))
        breakdowns.append({"title": title, "filter": filter_name, "rows": rows})

    return {
        "as_of": as_of,
        "count": in_force.count(),
        "commission": total["commission"],
        "premium": total["premium"],
        "horizon_end": as_of + timedelta(days=SNAPSHOT_HORIZON_DAYS - 1),
        "breakdowns": breakdowns,
    }


def _calendar(params):
    start = params.today.replace(day=1)
    end = _calendar_end(start)
    policies = portfolio.expiring(params.policies(), start, end)
    open_ids = set(
        policies.filter(portfolio.dfa_active_on_end_q()).values_list("id", flat=True)
    )
    months = {m: {"open": 0, "closed": 0} for m in money.month_starts(start, end)}
    for pk, end_date in policies.values_list("id", "end_date"):
        months[end_date.replace(day=1)]["open" if pk in open_ids else "closed"] += 1
    return [
        {
            "month": m,
            "code": f"{m:%Y-%m}",
            "label": f"{money.MONTH_SHORT[m.month - 1]} {m:%y}",
            **counts,
        }
        for m, counts in months.items()
    ]


def _churn(params):
    end = min(params.date_to, params.today)
    if params.date_from > end:
        return []
    policies = params.policies()
    loss_rows = money.lost_rows(params.payments())
    rows = []
    for q_start in portfolio.quarters_between(params.date_from, end):
        q_end = min(portfolio.quarter_end(q_start), end)
        q_losses = money.lost_in_period(loss_rows, q_start, q_end)
        rows.append(
            {
                "code": portfolio.quarter_code(q_start),
                "label": portfolio.quarter_label(q_start),
                "early": portfolio.early_buyouts(policies, q_start, q_end).count(),
                "terminated": portfolio.terminations(policies, q_start, q_end).count(),
                "early_kv": money.sum_rows(
                    [r for r in q_losses if r["reason"] == money.LOSS_EARLY_BUYOUT]
                )["commission"],
                "terminated_kv": money.sum_rows(
                    [r for r in q_losses if r["reason"] == money.LOSS_TERMINATION]
                )["commission"],
            }
        )
    return rows


def build(params, query=None):
    retention_end = min(params.date_to, params.today)
    retention = (
        portfolio.retention_by_quarter(
            params.policies(), params.date_from, retention_end
        )
        if params.date_from <= retention_end
        else []
    )
    calendar = _calendar(params)
    return {
        "snapshot": _snapshot(params),
        "calendar": calendar,
        "calendar_chart": {
            "labels": [row["label"] for row in calendar],
            "open": [row["open"] for row in calendar],
            "closed": [row["closed"] for row in calendar],
        },
        "retention": retention,
        "retention_total": {
            "due": sum(r["due"] for r in retention),
            "renewed": sum(r["renewed"] for r in retention),
            "switched": sum(r["switched"] for r in retention),
        },
        "churn": _churn(params),
        "window_days": portfolio.RENEWAL_WINDOW_DAYS,
    }
