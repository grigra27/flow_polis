"""
Вкладка «Каналы»: какие филиалы и менеджеры лизинга приводят бизнес
(docs/analytics-2.0-plan.md, §4 F).

Новый бизнес — за период и за тот же период год назад; полисы в силе и КВ
на 12 месяцев — на сегодня; продление и потери — за период.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count

from apps.policies.models import PaymentSchedule, in_force_q

from .. import money, portfolio
from .summary import MANAGER_MIN_PREVIOUS, same_day_last_year

USES_PERIOD = True

GROUPINGS = {
    "branch": ("branch_id", "branch__branch_name", "Филиал"),
    "manager": ("leasing_manager_id", "leasing_manager__name", "Менеджер лизинга"),
}
DEFAULT_GROUPING = "branch"
HORIZON_DAYS = 365
DROP_THRESHOLD = Decimal("-50")


def _new_business(policies, start, end, id_field):
    selected = portfolio.new_business(policies, start, end)
    counts = defaultdict(int)
    for key in selected.values_list(id_field, flat=True):
        counts[key] += 1
    kv = defaultdict(Decimal)
    for key, value in PaymentSchedule.objects.filter(
        policy__in=selected, year_number=1
    ).values_list(f"policy__{id_field}", "kv_rub"):
        kv[key] += value
    return counts, kv


def build(params, query=None):
    query = query or {}
    grouping = query.get("by") if query.get("by") in GROUPINGS else DEFAULT_GROUPING
    id_field, label_field, title = GROUPINGS[grouping]
    start, end, today = params.date_from, params.date_to, params.today
    policies = params.policies()
    payments = params.payments()

    names = dict(policies.values_list(id_field, label_field).distinct())
    nb_count, nb_kv = _new_business(policies, start, end, id_field)
    prev_start, prev_end = same_day_last_year(start), same_day_last_year(end)
    prev_count, prev_kv = _new_business(policies, prev_start, prev_end, id_field)
    history_ok = money.history_is_reliable(prev_start)

    in_force_qs = policies.filter(in_force_q(today))
    in_force = {
        row[id_field]: row["n"]
        for row in in_force_qs.values(id_field).annotate(n=Count("id")).order_by()
    }
    horizon_kv = defaultdict(Decimal)
    for key, value in (
        money.scheduled_payments(PaymentSchedule.objects.filter(policy__in=in_force_qs))
        .filter(due_date__gte=today, due_date__lt=today + timedelta(days=HORIZON_DAYS))
        .values_list(f"policy__{id_field}", "kv_rub")
    ):
        horizon_kv[key] += value

    retention_end = min(end, today)
    due_counts, renewed_counts = defaultdict(int), defaultdict(int)
    if start <= retention_end:
        due = portfolio.renewal_due(policies, start, retention_end)
        groups = dict(due.values_list("id", id_field))
        for pk, status in portfolio.renewal_statuses(due).items():
            due_counts[groups[pk]] += 1
            if status["status"] != portfolio.NOT_RENEWED:
                renewed_counts[groups[pk]] += 1

    losses = defaultdict(Decimal)
    for row in money.lost_in_period(
        money.lost_rows(payments, f"policy__{id_field}"), start, end
    ):
        losses[row[f"policy__{id_field}"]] += row["kv_rub"]

    keys = set(nb_count) | set(prev_count) | set(in_force) | set(losses)
    rows = []
    for key in keys:
        current, previous = nb_count.get(key, 0), prev_count.get(key, 0)
        change = (
            Decimal(current - previous) / previous * 100
            if history_ok and previous
            else None
        )
        rows.append(
            {
                "id": key,
                "name": names.get(key) or "Без менеджера",
                "nb_count": current,
                "nb_kv": nb_kv.get(key, Decimal("0")),
                "prev_count": previous,
                "prev_kv": prev_kv.get(key, Decimal("0")),
                "change": change,
                "dropped": change is not None
                and previous >= MANAGER_MIN_PREVIOUS
                and change <= DROP_THRESHOLD,
                "in_force": in_force.get(key, 0),
                "horizon_kv": horizon_kv.get(key, Decimal("0")),
                "renewal_due": due_counts.get(key, 0),
                "renewal_rate": (
                    renewed_counts.get(key, 0) / due_counts[key] * 100
                    if due_counts.get(key)
                    else None
                ),
                "lost": losses.get(key, Decimal("0")),
            }
        )
    rows.sort(key=lambda r: (-r["nb_kv"], -r["nb_count"], -r["in_force"]))
    return {
        "grouping": grouping,
        "grouping_title": title,
        "groupings": [{"key": k, "title": v[2]} for k, v in GROUPINGS.items()],
        "rows": rows,
        "history_ok": history_ok,
        "previous_from": prev_start,
        "previous_to": prev_end,
    }
