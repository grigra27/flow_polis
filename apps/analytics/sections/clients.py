"""
Вкладка «Клиенты»: насколько зависим от крупных клиентов и кто требует
внимания (docs/analytics-2.0-plan.md, §4 G).

Клиент — лизингополучатель (Policy.client). КВ клиента за период — по графику
(без отменённых), дата платежа в периоде. Новый клиент — первый полис
клиента начался в периоде.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Min

from apps.policies.models import in_force_q

from .. import money
from ..drilldown import POLICIES, metric

USES_PERIOD = True
TOP_CLIENTS = 50


@metric("client_policies", "Полисы клиента", POLICIES)
def client_policies(params, opts):
    queryset = params.policies()
    client = opts.get("client")
    if client and str(client).isdigit():
        return queryset.filter(client_id=int(client))
    return queryset.none()


def _top_share(values, n, total):
    return sum(values[:n], Decimal("0")) / total * 100 if total else None


def build(params, query=None):
    start, end, today = params.date_from, params.date_to, params.today
    policies = params.policies()
    payments = params.payments()

    kv = defaultdict(Decimal)
    names = {}
    for client_id, name, value in (
        money.scheduled_payments(payments)
        .filter(due_date__gte=start, due_date__lte=end)
        .values_list("policy__client_id", "policy__client__client_name", "kv_rub")
    ):
        kv[client_id] += value
        names[client_id] = name
    ranked = sorted(kv, key=lambda pk: -kv[pk])
    values = [kv[pk] for pk in ranked]
    total = sum(values, Decimal("0"))

    first_start = dict(
        policies.values("client_id")
        .annotate(first=Min("start_date"))
        .values_list("client_id", "first")
    )
    in_force = policies.filter(in_force_q(today))
    in_force_counts = dict(
        in_force.values("client_id")
        .annotate(n=Count("id"))
        .values_list("client_id", "n")
    )
    nearest_end = dict(
        in_force.values("client_id")
        .annotate(end=Min("end_date"))
        .values_list("client_id", "end")
    )
    expected = defaultdict(Decimal)
    for client_id, value in (
        money.expected_payments(payments)
        .filter(due_date__gte=today, policy__client_id__in=ranked[:TOP_CLIENTS])
        .values_list("policy__client_id", "kv_rub")
    ):
        expected[client_id] += value

    rows = [
        {
            "id": pk,
            "rank": index,
            "name": names[pk],
            "commission": kv[pk],
            "share": kv[pk] / total * 100 if total else None,
            "in_force": in_force_counts.get(pk, 0),
            "expected": expected.get(pk, Decimal("0")),
            "nearest_end": nearest_end.get(pk),
            "is_new": bool(first_start.get(pk)) and start <= first_start[pk] <= end,
        }
        for index, pk in enumerate(ranked[:TOP_CLIENTS], 1)
    ]

    cumulative, running = [], Decimal("0")
    for value in values:
        running += value
        cumulative.append(float(running / total * 100) if total else 0)

    return {
        "rows": rows,
        "clients_total": len(ranked),
        "total_commission": total,
        "top10_share": _top_share(values, 10, total),
        "top50_share": _top_share(values, 50, total),
        "new_clients": sum(
            1 for first in first_start.values() if first and start <= first <= end
        ),
        "pareto": {
            "labels": list(range(1, len(cumulative) + 1)),
            "values": cumulative,
        },
    }
