"""
Вкладка «ОСАГО»: полисы ОСАГО с датой начала в периоде (перенос страницы
«Аналитика ОСАГО» на общие фильтры раздела). Премия и КВ — по единственному
платежу полиса. Переключатель «с ОСАГО» на эту вкладку не влияет.
"""

from decimal import Decimal

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from apps.policies.models import PaymentSchedule, in_force_q

from .. import money
from ..drilldown import PAYMENTS, POLICIES, metric

USES_PERIOD = True
TOP_CLIENTS = 20


def _policies(params):
    return params.osago_policies().filter(
        start_date__gte=params.date_from, start_date__lte=params.date_to
    )


@metric("osago_policies", "Полисы ОСАГО с началом в периоде", POLICIES)
def osago_policies(params, opts):
    return _policies(params)


@metric("osago_in_force", "Полисы ОСАГО в силе сегодня", POLICIES)
def osago_in_force(params, opts):
    return params.osago_policies().filter(in_force_q(params.today))


@metric("osago_payments", "Платежи ОСАГО полисов периода", PAYMENTS)
def osago_payments(params, opts):
    return PaymentSchedule.objects.filter(policy__in=_policies(params))


def _breakdown(payments, id_field, label_field):
    return [
        {
            "id": row[id_field],
            "name": row[label_field] or "Не указано",
            "policies": row["policies"],
            "premium": row["premium"],
            "kv": row["kv"],
        }
        for row in payments.values(id_field, label_field)
        .annotate(
            policies=Count("policy", distinct=True),
            premium=money._money("amount"),
            kv=money._money("kv_rub"),
        )
        .order_by("-premium", label_field)
    ]


def build(params, query=None):
    policies = _policies(params)
    payments = PaymentSchedule.objects.filter(policy__in=policies)
    totals = payments.aggregate(
        premium=money._money("amount"),
        kv=money._money("kv_rub"),
        paid=Count("id", filter=Q(paid_date__isnull=False)),
        approved=Count("id", filter=Q(insurer_date__isnull=False)),
    )
    totals["policies"] = policies.count()
    totals["in_force"] = osago_in_force(params, {}).count()
    totals["kv_percent"] = (
        totals["kv"] / totals["premium"] * 100 if totals["premium"] else Decimal("0")
    )
    months = {
        row["month"]: row
        for row in payments.annotate(month=TruncMonth("policy__start_date"))
        .values("month")
        .annotate(
            policies=Count("policy", distinct=True),
            premium=money._money("amount"),
            kv=money._money("kv_rub"),
        )
        .order_by()
    }
    by_month = [
        {
            "label": f"{money.MONTH_NAMES[m.month - 1]} {m.year}",
            "policies": months.get(m, {}).get("policies", 0),
            "premium": months.get(m, {}).get("premium", Decimal("0")),
            "kv": months.get(m, {}).get("kv", Decimal("0")),
        }
        for m in money.month_starts(params.date_from, params.date_to)
    ]
    by_client = _breakdown(payments, "policy__client_id", "policy__client__client_name")
    return {
        "totals": totals,
        "by_month": by_month,
        "by_branch": _breakdown(
            payments, "policy__branch_id", "policy__branch__branch_name"
        ),
        "by_insurer": _breakdown(
            payments, "policy__insurer_id", "policy__insurer__insurer_name"
        ),
        "by_client": by_client[:TOP_CLIENTS],
        "clients_total": len(by_client),
    }
