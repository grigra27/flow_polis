"""
Регрессионная страховка перед добавлением ОСАГО (этап 0).

Фиксирует цифры отчётов и аналитики на эталонном портфеле без ОСАГО:
- test_baseline_* — значения, посчитанные вручную по фикстуре `portfolio`;
- portfolio_snapshot() — «слепок» выходов сервисов, которые по решению
  владельца (docs: вопросник ОСАГО, карта влияния) должны работать
  без ОСАГО. На следующих этапах тест-инвариант добавит в портфель полис
  ОСАГО и сравнит слепки до/после — они обязаны совпасть.
"""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

pytestmark = pytest.mark.integration


@pytest.fixture
def portfolio(db):
    """Эталонный портфель: 4 полиса, 7 платежей, КВ 10%.

    Даты считаются от сегодняшнего дня, чтобы «в силе» и деление на
    закрытые/текущие месяцы были предсказуемы:
    - P1: КАСКО, 3 года, начался 200 дней назад, 4 платежа (2 прошлых
      оплачены, 2 будущих);
    - P2: Спецтехника, 1 год, начался 30 дней назад, 1 платёж оплачен;
    - P3: КАСКО, истёк 36 дней назад, 1 платёж оплачен;
    - P4: КАСКО, начнётся через 10 дней, 1 платёж не оплачен.
    Все прошлые платежи оплачены, поэтому «мост» аналитики (факт закрытых
    месяцев + план текущего и будущих) равен сумме всех платежей.
    """
    from apps.clients.models import Client
    from apps.insurers.models import Branch, CommissionRate, InsuranceType, Insurer
    from apps.policies.models import PaymentSchedule, Policy

    today = timezone.localdate()

    kasko = InsuranceType.objects.create(name="КАСКО")
    special = InsuranceType.objects.create(name="Спецтехника")
    insurer_a = Insurer.objects.create(insurer_name="СК Альфа")
    insurer_b = Insurer.objects.create(insurer_name="СК Бета")
    branch_x = Branch.objects.create(branch_name="Москва")
    branch_y = Branch.objects.create(branch_name="Казань")
    c1 = Client.objects.create(client_name="ООО Первый", client_inn="7700000001")
    c2 = Client.objects.create(client_name="ООО Второй", client_inn="7700000002")
    c3 = Client.objects.create(client_name="ООО Третий", client_inn="7700000003")

    rates = {}
    for insurer in (insurer_a, insurer_b):
        for ins_type in (kasko, special):
            rates[(insurer.pk, ins_type.pk)] = CommissionRate.objects.create(
                insurer=insurer, insurance_type=ins_type, kv_percent=Decimal("10")
            )

    def make_policy(number, client, insurer, branch, ins_type, start, end, payments):
        policy = Policy.objects.create(
            policy_number=number,
            dfa_number=f"ДФА-{number}",
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=ins_type,
            property_description=f"Имущество {number}",
            start_date=start,
            end_date=end,
        )
        rate = rates[(insurer.pk, ins_type.pk)]
        for year, inst, due, ins_sum, amount, paid in payments:
            PaymentSchedule.objects.create(
                policy=policy,
                year_number=year,
                installment_number=inst,
                due_date=due,
                insurance_sum=Decimal(ins_sum),
                amount=Decimal(amount),
                commission_rate=rate,
                kv_rub=Decimal(amount) / 10,
                paid_date=due if paid else None,
            )
        return policy

    p1_start = today - timedelta(days=200)
    make_policy(
        "P1",
        c1,
        insurer_a,
        branch_x,
        kasko,
        p1_start,
        p1_start + timedelta(days=3 * 365 - 1),
        [
            (1, 1, p1_start, "3000000", "60000", True),
            (1, 2, p1_start + timedelta(days=182), "3000000", "60000", True),
            (2, 1, p1_start + timedelta(days=365), "2700000", "100000", False),
            (3, 1, p1_start + timedelta(days=730), "2400000", "90000", False),
        ],
    )
    p2_start = today - timedelta(days=30)
    make_policy(
        "P2",
        c2,
        insurer_b,
        branch_y,
        special,
        p2_start,
        p2_start + timedelta(days=364),
        [(1, 1, p2_start, "5000000", "50000", True)],
    )
    p3_start = today - timedelta(days=400)
    make_policy(
        "P3",
        c3,
        insurer_a,
        branch_y,
        kasko,
        p3_start,
        today - timedelta(days=36),
        [(1, 1, p3_start, "2000000", "40000", True)],
    )
    p4_start = today + timedelta(days=10)
    make_policy(
        "P4",
        c1,
        insurer_b,
        branch_x,
        kasko,
        p4_start,
        p4_start + timedelta(days=364),
        [(1, 1, p4_start, "3500000", "70000", False)],
    )

    return {
        "today": today,
        "insurers": (insurer_a, insurer_b),
        "branches": (branch_x, branch_y),
        "types": (kasko, special),
        "clients": (c1, c2, c3),
    }


def add_osago_policy(portfolio):
    """Добавляет действующий полис ОСАГО к тем же СК, филиалу и клиенту, что у P1.

    Если ОСАГО просочится в раздел «без ОСАГО», изменятся цифры по
    «СК Альфа», «Москва» и «ООО Первый».
    """
    from apps.insurers.models import CommissionRate, InsuranceType
    from apps.policies.models import PaymentSchedule, Policy

    insurer_a = portfolio["insurers"][0]
    osago_type = InsuranceType.objects.create(name="ОСАГО (регрессия)", is_osago=True)
    rate = CommissionRate.objects.create(
        insurer=insurer_a, insurance_type=osago_type, kv_percent=Decimal("10")
    )
    start = portfolio["today"] - timedelta(days=10)
    policy = Policy.objects.create(
        policy_number="OSAGO-R1",
        dfa_number="ДФА-P1",
        client=portfolio["clients"][0],
        insurer=insurer_a,
        branch=portfolio["branches"][0],
        insurance_type=osago_type,
        property_description="Имущество P1",
        start_date=start,
        end_date=start + timedelta(days=364),
        franchise=Decimal("0"),
    )
    PaymentSchedule.objects.create(
        policy=policy,
        year_number=1,
        installment_number=1,
        due_date=start,
        insurance_sum=None,
        amount=Decimal("15000"),
        commission_rate=rate,
        kv_rub=Decimal("1500"),
        paid_date=start,
    )
    return policy


def _normalize(value):
    """Приводит выход сервиса к сравнимому виду (Decimal, даты, модели → str)."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def portfolio_snapshot(portfolio):
    """Слепок выходов, которые по карте влияния должны быть БЕЗ ОСАГО."""
    from apps.analytics.services import AnalyticsService
    from apps.core.services.dashboard_v2_service import DashboardV2Service
    from apps.insurers.services.statistics import (
        BranchStatisticsService,
        InsurerStatisticsService,
    )
    from apps.reports.services.property_snapshot import build_property_snapshot

    cache.clear()
    service = AnalyticsService()
    dashboard_v2 = DashboardV2Service().get_dashboard_context()

    insurer_stats = {}
    for insurer in portfolio["insurers"]:
        filters = InsurerStatisticsService.parse_filters(
            selected_branch_id=None,
            selected_insurance_type_id=None,
            stats_scope="all",
            policy_scope="all",
            metric="premium",
            date_from=None,
            date_to=None,
        )
        insurer_stats[insurer.insurer_name] = InsurerStatisticsService(
            insurer
        ).calculate(filters)

    branch_stats = {}
    for branch in portfolio["branches"]:
        filters = BranchStatisticsService.parse_filters(
            selected_insurer_id=None,
            selected_insurance_type_id=None,
            stats_scope="all",
            policy_scope="all",
            metric="premium",
            date_from=None,
            date_to=None,
        )
        branch_stats[branch.branch_name] = BranchStatisticsService(branch).calculate(
            filters
        )

    snapshot = {
        "analytics_dashboard": service.get_dashboard_metrics(),
        "analytics_branches": service.get_branch_analytics(),
        "analytics_branches_v2": service.get_branch_portfolio_analytics_v2(),
        "analytics_insurers": service.get_insurer_analytics(),
        "analytics_clients": service.get_client_analytics(),
        "property_snapshot": build_property_snapshot(),
        # Структура портфеля на главной — С ОСАГО (решение владельца),
        # поэтому в слепок не входит; концентрация и индекс нового бизнеса — без.
        "dashboard_v2_concentration": dashboard_v2["dashboard_v2_concentration"],
        "dashboard_v2_nb_index": dashboard_v2["dashboard_v2_nb_index"],
        "insurer_statistics": insurer_stats,
        "branch_statistics": branch_stats,
    }
    cache.clear()
    return _normalize(snapshot)


def test_baseline_dashboard_metrics(portfolio):
    from apps.analytics.services import AnalyticsService

    cache.clear()
    metrics = AnalyticsService().get_dashboard_metrics()

    assert "error" not in metrics
    # Все прошлые платежи оплачены → мост = сумма всех 7 платежей.
    assert metrics["total_premium_volume"] == Decimal("470000")
    assert metrics["total_commission_revenue"] == Decimal("47000")
    # СС полиса = максимум по графику: 3.0 + 5.0 + 2.0 + 3.5 млн.
    assert metrics["total_insurance_sum"] == Decimal("13500000")
    assert metrics["total_policy_count"] == 4
    # В силе сегодня: P1 и P2 (P3 истёк, P4 ещё не начался).
    assert metrics["active_policies_count"] == 2
    assert metrics["average_commission_rate"] == Decimal("10")


def test_baseline_rates_by_year(portfolio):
    from apps.policies.models import Policy

    rates = Policy.objects.get(policy_number="P1").get_rates_by_year()

    # Год 1: 120 000 / 3 000 000 = 4%; год 2: 100 000 / 2 700 000; год 3: 90 000 / 2 400 000.
    assert [r["year_number"] for r in rates] == [1, 2, 3]
    assert rates[0]["total_premium"] == Decimal("120000")
    assert rates[0]["rate"] == Decimal("4")
    assert rates[0]["is_current"] is True


def test_snapshot_services_return_real_data(portfolio):
    """Сервисы слепка отрабатывают без ошибок и видят данные портфеля.

    Многие сервисы аналитики при исключении возвращают нули с ключом
    "error" — такой слепок бесполезен для сравнения, поэтому ловим это явно.
    """
    snapshot = portfolio_snapshot(portfolio)

    for key, value in snapshot.items():
        assert value is not None, key
        if isinstance(value, dict):
            assert "error" not in value, (key, value.get("error"))

    assert snapshot["analytics_dashboard"]["total_policy_count"] == 4
    assert Decimal(str(snapshot["analytics_dashboard"]["total_insurance_sum"])) == (
        Decimal("13500000")
    )


def test_snapshot_is_deterministic(portfolio):
    """Два слепка подряд совпадают — основа для сравнения «до/после ОСАГО»."""
    assert portfolio_snapshot(portfolio) == portfolio_snapshot(portfolio)


def test_osago_policy_does_not_change_osago_free_sections(portfolio):
    """Весь слепок — разделы «без ОСАГО»: полис ОСАГО не меняет ни одной цифры."""
    before = portfolio_snapshot(portfolio)
    add_osago_policy(portfolio)
    after = portfolio_snapshot(portfolio)

    assert after.keys() == before.keys()
    for key in before:
        assert after[key] == before[key], key
