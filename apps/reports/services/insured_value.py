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
Если год или его страховая сумма не определены, значение неизвестно:
максимальная сумма другого года не подставляется.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from django.utils import timezone

from apps.policies.models import PaymentSchedule, Policy, in_force_q
from apps.core.services.portfolio_scope import (
    PortfolioScope,
    dfa_in_force_q,
    normalize_scope,
)

ZERO = Decimal("0")


def current_insured_sums(policy_ids: Iterable[int], as_of: date) -> Dict[int, Decimal]:
    """{id полиса: страховая сумма текущего года на as_of}."""
    rows = PaymentSchedule.objects.filter(policy_id__in=list(policy_ids)).values_list(
        "policy_id", "year_number", "installment_number", "due_date", "insurance_sum"
    )
    return select_current_insured_sums(rows, as_of)


def select_current_insured_sums(rows, as_of: date) -> Dict[int, Decimal]:
    """Общий расчёт для отчётов и Dashboard, включая неполные графики.

    Сначала определяем текущий год, даже если его СС отсутствует. Иначе NULL
    у нового года незаметно заменялся бы стоимостью предыдущего года.
    """
    current: Dict[int, tuple] = {}
    started_years: Dict[int, int] = {}
    for policy_id, year, installment, due, value in rows:
        if due <= as_of:
            started_years[policy_id] = max(year, started_years.get(policy_id, 0))
        if installment == 1 and due <= as_of:
            if policy_id not in current or year > current[policy_id][0]:
                current[policy_id] = (year, value)
    return {
        pk: value
        for pk, (year, value) in current.items()
        if value is not None and year == started_years[pk]
    }


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
    insured_sum_known: bool = True


def insured_portfolio(
    as_of: Optional[date] = None, branch_ids=None, structure_scope="all"
) -> List[InsuredObject]:
    """Объекты в силе на as_of с активным ДФА и их страховая стоимость."""
    as_of = as_of or timezone.localdate()
    policies = (
        Policy.objects.without_osago()
        .filter(in_force_q(as_of), dfa_in_force_q(as_of))
        .select_related(
            "client", "insurer", "branch", "insurance_type", "leasing_manager"
        )
        .only(
            "policy_number",
            "dfa_number",
            "client__client_name",
            "insurer__insurer_name",
            "branch__branch_name",
            "insurance_type__name",
            "leasing_manager__name",
            "property_description",
            "property_year",
            "franchise",
            "start_date",
            "end_date",
        )
    )
    policies = PortfolioScope(
        as_of, normalize_scope(structure_scope), tuple(branch_ids or ())
    ).apply(policies)
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
            insured_sum_known=p.id in sums,
        )
        for p in policies
    ]
