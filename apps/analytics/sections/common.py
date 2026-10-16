"""Общие величины, не привязанные к одной вкладке."""

from apps.policies.models import in_force_q

from ..drilldown import PAYMENTS, POLICIES, metric


@metric("payments_due", "Платежи по графику за период", PAYMENTS)
def payments_due(params, opts):
    return params.payments().filter(
        due_date__gte=params.date_from, due_date__lte=params.date_to
    )


@metric("in_force", "Полисы в силе на дату среза", POLICIES)
def in_force(params, opts):
    return params.policies().filter(in_force_q(params.as_of))


@metric(
    "non_broker",
    "Полисы без участия брокера",
    POLICIES,
    note="Исключены из всех показателей раздела.",
)
def non_broker(params, opts):
    return params.non_broker_policies()
