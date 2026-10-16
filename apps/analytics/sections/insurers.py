"""
Вкладка «Страховщики»: с кем выгодно работать и с кем есть проблемы
(docs/analytics-2.0-plan.md, §4 E). Одна таблица, строка — СК.

- КВ за период — по графику (без отменённых), дата платежа в периоде;
- КВ % — КВ / премия тех же платежей, по видам страхования;
- тариф — медиана «премия 1-го года / страховая сумма» новых полисов периода;
- дни до акта — медиана «акт − оплата» по актам периода;
- ждёт акта — срез на сегодня; потеряно — по дате события в периоде;
- доля в новом бизнесе — по числу новых полисов, к тому же периоду год назад.
"""

from collections import defaultdict
from decimal import Decimal
from statistics import median

from django.db.models import Count

from apps.policies.models import PaymentSchedule, in_force_q

from .. import money, portfolio
from .summary import same_day_last_year

USES_PERIOD = True
MAX_TYPE_COLUMNS = 3


def _share(part, total):
    return part / total * 100 if total else None


def _new_business_share(policies, start, end):
    counts = defaultdict(int)
    for insurer_id in portfolio.new_business(policies, start, end).values_list(
        "insurer_id", flat=True
    ):
        counts[insurer_id] += 1
    total = sum(counts.values())
    return {pk: _share(Decimal(n), Decimal(total)) for pk, n in counts.items()}, total


def _tariffs(policies, start, end):
    """{(insurer_id, type_id): медиана тарифа 1-го года, %} по новым полисам периода."""
    per_policy = {}
    for row in PaymentSchedule.objects.filter(
        policy__in=portfolio.new_business(policies, start, end), year_number=1
    ).values(
        "policy_id",
        "policy__insurer_id",
        "policy__insurance_type_id",
        "installment_number",
        "insurance_sum",
        "amount",
    ):
        item = per_policy.setdefault(
            row["policy_id"],
            {
                "key": (row["policy__insurer_id"], row["policy__insurance_type_id"]),
                "premium": Decimal("0"),
                "sum": None,
            },
        )
        item["premium"] += row["amount"]
        if row["installment_number"] == 1:
            item["sum"] = row["insurance_sum"]
    rates = defaultdict(list)
    for item in per_policy.values():
        if item["sum"]:
            rates[item["key"]].append(item["premium"] / item["sum"] * 100)
    return {key: median(values) for key, values in rates.items()}


def _act_lag(payments, start, end):
    lags = defaultdict(list)
    for insurer_id, paid, act in (
        money.earned_payments(payments, start, end)
        .filter(paid_date__isnull=False)
        .values_list("policy__insurer_id", "paid_date", "insurer_date")
    ):
        lags[insurer_id].append((act - paid).days)
    return {pk: median(values) for pk, values in lags.items()}


def build(params, query=None):
    start, end, today = params.date_from, params.date_to, params.today
    payments = params.payments()
    policies = params.policies()

    in_period = money.scheduled_payments(payments).filter(
        due_date__gte=start, due_date__lte=end
    )
    totals_by_insurer = {}
    by_type = defaultdict(dict)
    type_totals = defaultdict(Decimal)
    type_names = {}
    for row in (
        in_period.values(
            "policy__insurer_id",
            "policy__insurer__insurer_name",
            "policy__insurance_type_id",
            "policy__insurance_type__name",
        )
        .annotate(premium=money._money("amount"), commission=money._money("kv_rub"))
        .order_by()
    ):
        insurer_id = row["policy__insurer_id"]
        type_id = row["policy__insurance_type_id"]
        item = totals_by_insurer.setdefault(
            insurer_id,
            {
                "name": row["policy__insurer__insurer_name"],
                "premium": Decimal("0"),
                "commission": Decimal("0"),
            },
        )
        item["premium"] += row["premium"]
        item["commission"] += row["commission"]
        by_type[insurer_id][type_id] = _share(row["commission"], row["premium"])
        type_totals[type_id] += row["commission"]
        type_names[type_id] = row["policy__insurance_type__name"]
    types = sorted(type_totals, key=lambda pk: -type_totals[pk])[:MAX_TYPE_COLUMNS]
    total_kv = sum((i["commission"] for i in totals_by_insurer.values()), Decimal("0"))

    in_force = {
        row["insurer_id"]: row["n"]
        for row in policies.filter(in_force_q(today))
        .values("insurer_id")
        .annotate(n=Count("id"))
        .order_by()
    }
    debt = {
        row["insurer_id"]: row for row in money.awaiting_act_by_insurer(payments, today)
    }
    losses = defaultdict(Decimal)
    for row in money.lost_in_period(
        money.lost_rows(payments, "policy__insurer_id"), start, end
    ):
        losses[row["policy__insurer_id"]] += row["kv_rub"]
    tariffs = _tariffs(policies, start, end)
    lags = _act_lag(payments, start, end)
    nb_share, nb_total = _new_business_share(policies, start, end)
    prev_start, prev_end = same_day_last_year(start), same_day_last_year(end)
    nb_prev, _ = _new_business_share(policies, prev_start, prev_end)
    history_ok = money.history_is_reliable(prev_start)

    names = {pk: item["name"] for pk, item in totals_by_insurer.items()}
    for pk, name in policies.values_list(
        "insurer_id", "insurer__insurer_name"
    ).distinct():
        names.setdefault(pk, name)
    insurer_ids = set(totals_by_insurer) | set(in_force) | set(debt) | set(nb_share)

    rows = []
    for pk in insurer_ids:
        item = totals_by_insurer.get(
            pk, {"premium": Decimal("0"), "commission": Decimal("0")}
        )
        share_now = nb_share.get(pk)
        share_prev = nb_prev.get(pk)
        rows.append(
            {
                "id": pk,
                "name": names.get(pk, "—"),
                "in_force": in_force.get(pk, 0),
                "commission": item["commission"],
                "share": _share(item["commission"], total_kv),
                "kv_percent": _share(item["commission"], item["premium"]),
                "kv_by_type": [by_type[pk].get(t) for t in types],
                "tariff_by_type": [tariffs.get((pk, t)) for t in types],
                "act_lag": lags.get(pk),
                "awaiting": debt[pk]["commission"] if pk in debt else Decimal("0"),
                "awaiting_90": debt[pk]["over_90"] if pk in debt else Decimal("0"),
                "lost": losses.get(pk, Decimal("0")),
                "nb_share": share_now,
                "nb_share_change": (
                    (share_now or 0) - (share_prev or 0)
                    if history_ok and (share_now or share_prev)
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: (-r["commission"], -r["in_force"]))
    return {
        "rows": rows,
        "types": [type_names[t] for t in types],
        "total_commission": total_kv,
        "new_business_total": nb_total,
        "history_ok": history_ok,
        "previous_from": prev_start,
        "previous_to": prev_end,
    }
