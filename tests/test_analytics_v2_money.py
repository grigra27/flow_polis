"""
Аналитика 2.0, этап 2: словарь денег (потери, долг СК по актам, обеспечено),
вкладки «Деньги» и «Сводка» (docs/analytics-2.0-plan.md, §3.1, §4 A–B).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.http import QueryDict

from apps.analytics import drilldown, money
from apps.analytics.filters import AnalyticsParams
from apps.analytics.sections import money as money_tab
from apps.analytics.sections import summary as summary_tab
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TODAY = date(2026, 10, 16)


def params(query=""):
    return AnalyticsParams.from_query(QueryDict(query), today=TODAY)


@pytest.fixture
def refs(db):
    return {
        "client": Client.objects.create(
            client_name="ООО Тест", client_inn="7700000077"
        ),
        "insurer_a": Insurer.objects.create(insurer_name="СК А"),
        "insurer_b": Insurer.objects.create(insurer_name="СК Б"),
        "branch": Branch.objects.create(branch_name="Филиал"),
        "type": InsuranceType.objects.create(name="КАСКО (v2)"),
    }


@pytest.fixture
def make(refs):
    counter = {"n": 0}

    def make_policy(
        payments,
        start=date(2025, 1, 1),
        end=date(2028, 12, 31),
        insurer="insurer_a",
        policy_active=True,
        termination=None,
        dfa_active=True,
        dfa_closed_on=None,
        broker=True,
        manager=None,
        to_old_dfa=False,
    ):
        """payments: [(kv, due, paid, act), ...]; премия = КВ × 4, год 1."""
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"V2-{counter['n']}",
            dfa_number=f"ДФА-V2-{counter['n']}",
            client=refs["client"],
            insurer=refs[insurer],
            branch=refs["branch"],
            insurance_type=refs["type"],
            property_description="Имущество",
            start_date=start,
            end_date=end,
            policy_active=policy_active,
            termination_date=termination,
            dfa_active=dfa_active,
            dfa_deactivation_date=dfa_closed_on,
            broker_participation=broker,
            leasing_manager=manager,
            renewal_to_old_dfa=to_old_dfa,
        )
        for index, (kv, due, paid, act) in enumerate(payments, 1):
            PaymentSchedule.objects.create(
                policy=policy,
                year_number=1,
                installment_number=index,
                due_date=due,
                insurance_sum=Decimal("1000000"),
                amount=Decimal(kv) * 4,
                kv_rub=Decimal(kv),
                paid_date=paid,
                insurer_date=act,
            )
        return policy

    return make_policy


# --- причины потерь ------------------------------------------------------------


def _row(**kwargs):
    row = {
        "policy__termination_date": None,
        "policy__dfa_active": True,
        "policy__dfa_deactivation_date": None,
        "policy__end_date": date(2027, 6, 30),
    }
    row.update(kwargs)
    return row


@pytest.mark.unit
@pytest.mark.parametrize(
    "row, expected",
    [
        (
            _row(policy__termination_date=date(2026, 3, 1)),
            (money.LOSS_TERMINATION, date(2026, 3, 1)),
        ),
        (  # расторжение важнее закрытия ДФА
            _row(
                policy__termination_date=date(2026, 3, 1),
                policy__dfa_active=False,
                policy__dfa_deactivation_date=date(2026, 2, 1),
            ),
            (money.LOSS_TERMINATION, date(2026, 3, 1)),
        ),
        (  # 31 день до окончания — досрочный выкуп
            _row(
                policy__dfa_active=False,
                policy__dfa_deactivation_date=date(2027, 5, 30),
            ),
            (money.LOSS_EARLY_BUYOUT, date(2027, 5, 30)),
        ),
        (  # ровно 30 дней — ещё плановое закрытие
            _row(
                policy__dfa_active=False,
                policy__dfa_deactivation_date=date(2027, 5, 31),
            ),
            (money.LOSS_PLANNED_CLOSE, date(2027, 5, 31)),
        ),
        (
            _row(policy__dfa_active=False),
            (money.LOSS_UNKNOWN, None),
        ),
    ],
)
def test_classify_loss(row, expected):
    assert money.classify_loss(row) == expected


def test_dfa_closed_without_date_cancels_unpaid_payments(make):
    make(
        [
            (50, date(2026, 1, 1), date(2026, 1, 1), None),
            (100, date(2026, 12, 1), None, None),
        ],
        dfa_active=False,
    )
    payments = PaymentSchedule.objects.all()
    assert money._totals(money.expected_payments(payments))["count"] == 0
    rows = money.lost_rows(payments)
    assert [(r["kv_rub"], r["reason"], r["loss_date"]) for r in rows] == [
        (Decimal("100"), money.LOSS_UNKNOWN, None)
    ]


# --- разбиение всех платежей ---------------------------------------------------


@pytest.fixture
def mixed(make):
    """Платежи во всех состояниях, всего КВ 1+2+4+…+512 = 1023."""
    make([(1, date(2026, 2, 1), date(2026, 2, 1), date(2026, 3, 1))])  # заработано
    make([(2, date(2026, 9, 1), date(2026, 9, 1), None)])  # ждёт акта, 45 дн.
    make(
        [(4, date(2026, 5, 1), date(2026, 5, 2), None)], insurer="insurer_b"
    )  # 167 дн.
    make([(8, date(2026, 11, 1), None, None)])  # ожидается
    make([(16, date(2027, 3, 1), None, None)])  # ожидается, обеспечено 2027
    make([(32, date(2026, 10, 1), None, None)])  # просрочено
    make(  # потеряно: досрочный выкуп в августе
        [(64, date(2026, 12, 1), None, None)],
        dfa_active=False,
        dfa_closed_on=date(2026, 8, 10),
    )
    make(  # потеряно: расторжение в мае
        [(128, date(2026, 6, 1), None, None)],
        policy_active=False,
        termination=date(2026, 5, 20),
    )
    make(  # без участия брокера — исключён везде
        [(256, date(2026, 4, 1), date(2026, 4, 1), date(2026, 4, 20))], broker=False
    )
    make(  # плановое закрытие ДФА в сентябре (за 10 дней до окончания)
        [(512, date(2026, 10, 1), None, None)],
        end=date(2026, 9, 30),
        start=date(2025, 10, 1),
        dfa_active=False,
        dfa_closed_on=date(2026, 9, 20),
    )


def test_states_partition_all_payments(mixed):
    p = params()
    payments = p.payments()
    earned = money._totals(money.earned_payments(payments, date.min, date.max))
    awaiting = money._totals(money.awaiting_act_payments(payments))
    expected = money._totals(
        money.expected_payments(payments).filter(due_date__gte=TODAY)
    )
    overdue = money._totals(money_tab.overdue(p, {}))
    lost = money.sum_rows(money.lost_rows(payments))
    parts = [earned, awaiting, expected, overdue, lost]

    assert [part["commission"] for part in parts] == [1, 6, 24, 32, 704]
    assert sum(part["count"] for part in parts) == payments.count() == 9
    assert sum(part["commission"] for part in parts) == 1023 - 256


def test_awaiting_act_by_insurer_buckets(mixed):
    rows = money.awaiting_act_by_insurer(params().payments(), TODAY)
    # Сначала СК с долгом 90+.
    assert [r["insurer"] for r in rows] == ["СК Б", "СК А"]
    b, a = rows
    assert {x["key"]: x["commission"] for x in b["buckets"]}["90+"] == 4
    assert {x["key"]: x["commission"] for x in a["buckets"]}["31-60"] == 2
    assert b["oldest_days"] == (TODAY - date(2026, 5, 2)).days


def test_secured_and_forecast(mixed):
    payments = params().payments()
    assert [
        (r["year"], r["commission"]) for r in money.secured_by_year(payments, TODAY)
    ] == [(2027, Decimal("16"))]
    forecast = money.expected_by_month(payments, TODAY)
    assert len(forecast) == 12
    assert forecast[0]["month"] == date(2026, 10, 1)
    assert forecast[0]["commission"] == 0  # просрочка 1 октября не прогноз
    assert forecast[1]["commission"] == 8
    assert forecast[5]["commission"] == 16  # март 2027


def test_monthly_earned_vs_plan(mixed):
    rows = money.monthly_earned_vs_plan(
        params().payments(), date(2026, 1, 1), date(2026, 12, 31)
    )
    by_month = {r["month"].month: r for r in rows}
    assert len(rows) == 12
    assert by_month[3]["earned_commission"] == 1
    assert by_month[2]["plan_commission"] == 1
    # План без отменённых: потерянные 64/128/512 в план не входят.
    assert by_month[12]["plan_commission"] == 0
    assert by_month[6]["plan_commission"] == 0


# --- вкладка «Деньги» ----------------------------------------------------------


def test_money_tab_kpi_and_lists_agree(mixed):
    p = params()
    data = money_tab.build(p)
    kpi = data["kpi"]
    assert kpi["earned"]["commission"] == 1
    assert kpi["awaiting"]["commission"] == 6
    assert kpi["expected"]["commission"] == 8  # до 31.12.2026
    assert kpi["overdue"]["commission"] == 32
    assert kpi["lost"]["commission"] == 704
    reasons = {r["key"]: r["commission"] for r in data["loss_reasons"]}
    assert reasons == {
        money.LOSS_EARLY_BUYOUT: 64,
        money.LOSS_PLANNED_CLOSE: 512,
        money.LOSS_TERMINATION: 128,
        money.LOSS_UNKNOWN: 0,
    }
    assert data["non_broker"]["commission"] == 256

    for key in ["earned", "expected", "awaiting_act", "overdue", "lost"]:
        qs = drilldown.resolve(key, p)
        assert (
            money._totals(qs)["commission"]
            == kpi[{"awaiting_act": "awaiting"}.get(key, key)]["commission"]
        ), key


def test_lost_list_options(mixed):
    p = params()
    total = lambda opts: money._totals(drilldown.resolve("lost", p, opts))["commission"]
    assert total({"reason": money.LOSS_TERMINATION}) == 128
    assert total({"month": "2026-08"}) == 64
    assert total({"month": "2026-07"}) == 0
    assert total({"undated": "1"}) == 0
    # Период прошлого года — потерь нет.
    assert (
        money._totals(drilldown.resolve("lost", params("period=prev_year")))["count"]
        == 0
    )


def test_awaiting_act_list_age_options(mixed):
    p = params()
    total = lambda opts: money._totals(drilldown.resolve("awaiting_act", p, opts))[
        "commission"
    ]
    assert total({}) == 6
    assert total({"age": "90+"}) == 4
    assert total({"age": "31-60"}) == 2
    assert total({"age": "60+"}) == 4


# --- вкладка «Сводка» ----------------------------------------------------------


def test_summary_bridge_and_signals(mixed, make):
    manager = LeasingManager.objects.create(
        name="Падающий", branch=Branch.objects.first()
    )
    for days_ago in (100, 110, 120, 130, 140):  # 5 полисов в прошлом окне
        start = TODAY - timedelta(days=days_ago)
        make([(1, start, start, start)], start=start, manager=manager)
    start = TODAY - timedelta(days=10)
    make([(1, start, start, None)], start=start, manager=manager)  # 1 в последнем
    make(  # заканчивается через 30 дней, ДФА активен
        [(1, date(2025, 11, 20), date(2025, 11, 20), date(2025, 12, 1))],
        start=date(2025, 11, 15),
        end=TODAY + timedelta(days=30),
    )

    data = summary_tab.build(params())
    bridge = data["bridge"]
    assert bridge["projected_full_year_commission"] == (
        bridge["earned_commission"]
        + bridge["awaiting_act_commission"]
        + bridge["scheduled_commission"]
    )
    assert data["lost_ytd"]["commission"] == 704

    signals = data["signals"]
    assert signals["stale_act"]["commission"] == 4
    assert signals["stale_act"]["insurers"] == ["СК Б"]
    assert signals["ending_soon"]["count"] == 1
    assert [m["name"] for m in signals["manager_drops"]["rows"]] == ["Падающий"]
    # Последние 30 дней: плановое закрытие ДФА 20.09.
    assert signals["recent_losses"]["commission"] == 512


def test_summary_hides_growth_on_incomplete_history(mixed):
    data = summary_tab.build(params())
    # Прошлый год начинается 01.01.2025 — раньше границы надёжной истории.
    assert data["ytd"]["history_incomplete"]
    assert data["ytd"]["change"] is None
    month = dict(data["new_business_rows"])["Месяц"]
    assert not month["history_incomplete"]  # октябрь 2025 — история полная
