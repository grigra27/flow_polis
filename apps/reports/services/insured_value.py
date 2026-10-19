"""
Страховая стоимость имущества лизинговой компании на дату среза.

Общая основа «Снэпшота по СС» и «Подробного отчёта по имуществу».

Портфель — полисы в силе на дату среза (in_force_q) с активным ДФА, без ОСАГО
(у ОСАГО нет страховой суммы). Полисы «без участия брокера» входят: для
лизингодателя это тоже его застрахованное имущество.

Страховая стоимость полиса — страховая сумма ТЕКУЩЕГО страхового года
(решение владельца 2026-10-17): у первого взноса последнего года, начавшегося
не позже даты среза. У многолетних полисов сумма с годами снижается, поэтому
максимум по графику (сумма первого года) завышал портфель примерно на 5%.
Если первого взноса текущего года в графике нет, берётся максимальная сумма
по графику.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from django.utils import timezone

from apps.policies.models import PaymentSchedule, Policy, in_force_q

ZERO = Decimal("0")


def current_insured_sums(policy_ids: Iterable[int], as_of: date) -> Dict[int, Decimal]:
    """{id полиса: страховая сумма текущего года на as_of}."""
    current: Dict[int, tuple] = {}
    maximum: Dict[int, Decimal] = {}
    for policy_id, year, installment, due, value in PaymentSchedule.objects.filter(
        policy_id__in=list(policy_ids)
    ).values_list(
        "policy_id", "year_number", "installment_number", "due_date", "insurance_sum"
    ):
        if value is None:
            continue
        if value > maximum.get(policy_id, ZERO):
            maximum[policy_id] = value
        if installment == 1 and due <= as_of:
            if policy_id not in current or year > current[policy_id][0]:
                current[policy_id] = (year, value)
    result = {pk: value for pk, (_, value) in current.items()}
    for pk, value in maximum.items():
        result.setdefault(pk, value)
    return result


@dataclass
class InsuredObject:
    id: int
    policy_number: str
    dfa_number: str
    client_id: int
    client: str
    insurer_id: int
    insurer: str
    branch_id: int
    branch: str
    type_id: int
    type: str
    manager_id: Optional[int]
    manager: str
    description: str
    property_year: Optional[int]
    franchise: Decimal
    start_date: date
    end_date: date
    insured_sum: Decimal


def insured_portfolio(
    as_of: Optional[date] = None, branch_ids=None
) -> List[InsuredObject]:
    """Объекты в силе на as_of с активным ДФА и их страховая стоимость."""
    as_of = as_of or timezone.localdate()
    policies = (
        Policy.objects.without_osago()
        .filter(in_force_q(as_of), dfa_active=True)
        .select_related(
            "client", "insurer", "branch", "insurance_type", "leasing_manager"
        )
    )
    if branch_ids:
        policies = policies.filter(branch_id__in=branch_ids)
    policies = list(policies)
    sums = current_insured_sums([p.id for p in policies], as_of)
    return [
        InsuredObject(
            id=p.id,
            policy_number=p.policy_number,
            dfa_number=p.dfa_number,
            client_id=p.client_id,
            client=p.client.client_name,
            insurer_id=p.insurer_id,
            insurer=p.insurer.insurer_name,
            branch_id=p.branch_id,
            branch=p.branch.branch_name,
            type_id=p.insurance_type_id,
            type=p.insurance_type.name,
            manager_id=p.leasing_manager_id,
            manager=p.leasing_manager.name if p.leasing_manager_id else "",
            description=p.property_description,
            property_year=p.property_year,
            franchise=p.franchise or ZERO,
            start_date=p.start_date,
            end_date=p.end_date,
            insured_sum=sums.get(p.id, ZERO),
        )
        for p in policies
    ]
