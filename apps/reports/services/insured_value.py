"""
Страховая стоимость имущества лизинговой компании на дату среза.

Общая основа «Снэпшота по СС» и «Подробного отчёта по имуществу».

Портфель — полисы в силе на дату среза (in_force_q) с активным ДФА, без ОСАГО
(у ОСАГО нет страховой суммы). Полисы «без участия брокера» входят: для
лизингодателя это тоже его застрахованное имущество.

Страховая стоимость полиса — страховая сумма ТЕКУЩЕГО страхового года
(решение владельца 2026-10-17): используется страховая сумма из первого
по порядку взноса текущего страхового года, у которого наступил договорный
срок и заполнена сумма. Взнос №1 не обязателен: если он отсутствует или пуст,
сумму восстанавливает следующий подходящий взнос того же года. У многолетних
полисов сумма с годами снижается, поэтому максимум по графику (сумма первого
года) завышал портфель примерно на 5%. Если год или его страховая сумма
не определены, значение неизвестно: суммы других лет не подставляются.
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

# Именованный вид существующего справочника; не определяем вид по описанию имущества.
LIABILITY_TYPE_NAME = "ответственность"


def is_liability_type(name: str) -> bool:
    """Вид страхования «Ответственность»: имя без регистра и внешних пробелов."""
    return name.strip().casefold() == LIABILITY_TYPE_NAME


def current_insured_sums(policy_ids: Iterable[int], as_of: date) -> Dict[int, Decimal]:
    """{id полиса: страховая сумма текущего года на as_of}."""
    rows = PaymentSchedule.objects.filter(policy_id__in=list(policy_ids)).values_list(
        "policy_id", "year_number", "installment_number", "due_date", "insurance_sum"
    )
    return select_current_insured_sums(rows, as_of)


def select_current_insured_sums(rows, as_of: date) -> Dict[int, Decimal]:
    """Общий расчёт для отчётов и Dashboard, включая неполные графики.

    Сначала определяем текущий год по всем строкам с наступившим сроком,
    даже если их СС пустая. Иначе NULL у нового года незаметно заменялся бы
    стоимостью предыдущего года. Внутри года берём первый по порядку взнос
    с наступившим договорным сроком и заполненной суммой: отсутствие взноса
    №1 само по себе не делает СС неизвестной. Будущие взносы не участвуют.
    """
    started_years: Dict[int, int] = {}
    started_rows: Dict[int, list] = {}
    for policy_id, year, installment, due, value in rows:
        if due <= as_of:
            started_years[policy_id] = max(year, started_years.get(policy_id, 0))
            started_rows.setdefault(policy_id, []).append((year, installment, value))
    result: Dict[int, Decimal] = {}
    for policy_id, year in started_years.items():
        value = first_filled_installment_sum(
            (installment, value)
            for row_year, installment, value in started_rows[policy_id]
            if row_year == year
        )
        if value is not None:
            result[policy_id] = value
    return result


def first_filled_installment_sum(installments) -> Optional[Decimal]:
    """СС взноса с наименьшим номером среди строк с заполненной суммой.

    Общий принцип выбора строки для среза портфеля и квартальных оплат;
    набор строк-кандидатов каждый отчёт готовит по своему правилу.
    Сохранённый ноль отличается от отсутствующего значения.
    """
    filled = [(number, value) for number, value in installments if value is not None]
    if not filled:
        return None
    return min(filled, key=lambda item: item[0])[1]


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
    needs_prolongation: bool = True
    dfa_deactivation_date: Optional[date] = None
    termination_date: Optional[date] = None


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
            "insurance_type__needs_prolongation",
            "dfa_deactivation_date",
            "termination_date",
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
            needs_prolongation=p.insurance_type.needs_prolongation,
            dfa_deactivation_date=p.dfa_deactivation_date,
            termination_date=p.termination_date,
        )
        for p in policies
    ]
