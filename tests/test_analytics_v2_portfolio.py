"""
Аналитика 2.0, этап 3: «Портфель и удержание» и «Продажи»
(docs/analytics-2.0-plan.md, §3.2, §4 C–D).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.http import QueryDict

from apps.analytics import drilldown, portfolio
from apps.analytics.filters import AnalyticsParams
from apps.analytics.sections import portfolio as portfolio_tab
from apps.analytics.sections import sales as sales_tab
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TODAY = date(2026, 10, 16)


def params(query=""):
    return AnalyticsParams.from_query(QueryDict(query), today=TODAY)


@pytest.fixture
def refs(db):
    branch = Branch.objects.create(branch_name="Псков")
    return {
        "client": Client.objects.create(client_name="ООО П", client_inn="7700000088"),
        "a": Insurer.objects.create(insurer_name="СК А"),
        "b": Insurer.objects.create(insurer_name="СК Б"),
        "branch": branch,
        "kasko": InsuranceType.objects.create(name="КАСКО (п)"),
        "osago": InsuranceType.objects.create(name="ОСАГО (п)", is_osago=True),
        "manager": LeasingManager.objects.create(name="Мишин", branch=branch),
    }


@pytest.fixture
def make(refs):
    counter = {"n": 0}

    def make_policy(
        start,
        end,
        dfa="ДФА-1",
        insurer="a",
        kind="kasko",
        kv=100,
        dfa_active=True,
        dfa_closed_on=None,
        termination=None,
        to_old_dfa=False,
        manager=True,
    ):
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"PT-{counter['n']}",
            dfa_number=dfa,
            client=refs["client"],
            insurer=refs[insurer],
            branch=refs["branch"],
            insurance_type=refs[kind],
            property_description="Техника",
            start_date=start,
            end_date=end,
            dfa_active=dfa_active,
            dfa_deactivation_date=dfa_closed_on,
            termination_date=termination,
            policy_active=termination is None,
            renewal_to_old_dfa=to_old_dfa,
            leasing_manager=refs["manager"] if manager else None,
        )
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=start,
            insurance_sum=None if kind == "osago" else Decimal("1000000"),
            amount=Decimal(kv) * (10 if kind == "osago" else 4),
            kv_rub=Decimal(kv),
        )
        return policy

    return make_policy


# --- продления -------------------------------------------------------------------


@pytest.fixture
def renewals(make):
    """III кв. 2026: 4 полиса требовали продления, 1 ушёл естественно."""
    q = {}
    q["renewed"] = make(date(2025, 7, 1), date(2026, 7, 10), dfa="100-ЛА")
    make(date(2026, 7, 11), date(2027, 7, 10), dfa=" 100-ла ")  # тот же ДФА
    q["switched"] = make(date(2025, 8, 1), date(2026, 8, 1), dfa="200-ЛА")
    make(date(2026, 7, 20), date(2027, 7, 19), dfa="200-ЛА", insurer="b")
    q["late"] = make(date(2025, 9, 1), date(2026, 9, 1), dfa="300-ЛА")
    make(date(2026, 10, 20), date(2027, 10, 19), dfa="300-ЛА")  # +49 дней — не в окне
    q["osago_successor"] = make(date(2025, 9, 5), date(2026, 9, 4), dfa="400-ЛА")
    make(date(2026, 9, 5), date(2027, 9, 4), dfa="400-ЛА", kind="osago", kv=10)
    # ДФА закрыт до окончания — продление не требуется.
    make(
        date(2025, 7, 15),
        date(2026, 7, 14),
        dfa="500-ЛА",
        dfa_active=False,
        dfa_closed_on=date(2026, 7, 1),
    )
    # Расторгнут — не «закончился по сроку».
    make(
        date(2025, 8, 1), date(2026, 8, 30), dfa="600-ЛА", termination=date(2026, 3, 1)
    )
    return q


def test_renewal_statuses(renewals):
    due = portfolio.renewal_due(
        Policy.objects.all(), date(2026, 7, 1), date(2026, 9, 30)
    )
    statuses = portfolio.renewal_statuses(due)
    by_id = {pk: s["status"] for pk, s in statuses.items()}
    assert by_id == {
        renewals["renewed"].pk: portfolio.RENEWED,
        renewals["switched"].pk: portfolio.SWITCHED,
        renewals["late"].pk: portfolio.NOT_RENEWED,
        renewals["osago_successor"].pk: portfolio.NOT_RENEWED,
    }


def test_retention_by_quarter(renewals):
    rows = portfolio.retention_by_quarter(Policy.objects.all(), date(2026, 7, 1), TODAY)
    q3 = rows[0]
    assert (
        q3["label"],
        q3["due"],
        q3["renewed"],
        q3["switched"],
        q3["not_renewed"],
    ) == (
        "III кв. 2026",
        4,
        2,
        1,
        2,
    )
    assert q3["rate"] == 50


def test_renewal_list_matches_table(renewals):
    p = params()
    data = portfolio_tab.build(p)
    q3 = next(r for r in data["retention"] if r["code"] == "2026Q3")
    for status, expected in [("renewed", 2), ("switched", 1), ("not_renewed", 2)]:
        qs = drilldown.resolve(
            "renewal_due", p, {"quarter": "2026Q3", "status": status}
        )
        assert qs.count() == expected == q3[status], status


# --- окончания, отток, срез -------------------------------------------------------


def test_calendar_splits_open_and_closed_dfa(make):
    make(date(2025, 11, 20), date(2026, 11, 19), dfa="A")
    make(
        date(2025, 11, 25),
        date(2026, 11, 24),
        dfa="B",
        dfa_active=False,
        dfa_closed_on=date(2026, 11, 24),
    )
    make(date(2026, 1, 10), date(2027, 1, 9), dfa="C")
    data = portfolio_tab.build(params())
    calendar = {r["code"]: r for r in data["calendar"]}
    assert len(data["calendar"]) == 12
    assert (calendar["2026-11"]["open"], calendar["2026-11"]["closed"]) == (1, 1)
    assert calendar["2027-01"]["open"] == 1
    p = params()
    assert (
        drilldown.resolve("expiring", p, {"month": "2026-11", "dfa": "open"}).count()
        == 1
    )
    assert (
        drilldown.resolve("expiring", p, {"month": "2026-11", "dfa": "closed"}).count()
        == 1
    )


def test_churn_early_buyout_threshold(make):
    make(  # 31 день до окончания — досрочный
        date(2025, 1, 1),
        date(2026, 9, 30),
        dfa="E1",
        dfa_active=False,
        dfa_closed_on=date(2026, 8, 30),
    )
    make(  # 30 дней — плановое, не отток
        date(2025, 1, 1),
        date(2026, 9, 30),
        dfa="E2",
        dfa_active=False,
        dfa_closed_on=date(2026, 8, 31),
    )
    make(date(2025, 1, 1), date(2027, 12, 31), dfa="E3", termination=date(2026, 5, 5))
    rows = {r["code"]: r for r in portfolio_tab.build(params())["churn"]}
    assert (rows["2026Q3"]["early"], rows["2026Q3"]["terminated"]) == (1, 0)
    assert (rows["2026Q2"]["early"], rows["2026Q2"]["terminated"]) == (0, 1)
    assert drilldown.resolve("churn", params(), {"quarter": "2026Q3"}).count() == 1


def test_snapshot_as_of(make):
    make(date(2025, 3, 1), date(2027, 2, 28), dfa="S1", kv=100)
    make(date(2026, 11, 1), date(2027, 10, 31), dfa="S2", kv=50)  # ещё не начался
    snapshot = portfolio_tab.build(params())["snapshot"]
    assert snapshot["count"] == 1
    # КВ на 12 мес.: у S1 платёж в прошлом, будущих нет.
    assert snapshot["commission"] == 0
    later = portfolio_tab.build(params("as_of=2026-11-15"))["snapshot"]
    assert later["count"] == 2
    assert later["commission"] == 0  # платёж S2 — 01.11, раньше среза


# --- продажи ---------------------------------------------------------------------


def test_sales_monthly_grouping_and_share(make):
    make(date(2026, 3, 5), date(2027, 3, 4), dfa="N1", kv=100)
    make(
        date(2026, 3, 20),
        date(2027, 3, 19),
        dfa="N2",
        kv=300,
        insurer="b",
        to_old_dfa=True,
    )
    make(date(2026, 5, 1), date(2027, 4, 30), dfa="N3", kv=600, manager=False)
    make(date(2025, 12, 1), date(2026, 11, 30), dfa="N0", kv=999)  # прошлый год

    data = sales_tab.build(params(), QueryDict("by=manager"))
    assert (data["totals"]["count"], data["totals"]["to_old_dfa"]) == (3, 1)
    assert data["totals"]["commission"] == 1000
    monthly = {r["month"].month: r for r in data["monthly"]}
    assert (monthly[3]["count"], monthly[3]["commission"]) == (2, 400)
    assert monthly[5]["commission"] == 600

    grouped = {r["name"]: r for r in data["grouped"]}
    assert grouped["Мишин"]["count"] == 2
    assert grouped["Не указан"]["commission"] == 600
    assert grouped["Не указан"]["share"] == 60

    share = data["insurer_share"]
    q1 = [q["label"] for q in share["quarters"]].index("I кв. 2026")
    assert sorted(r["shares"][q1] for r in share["rows"]) == [50, 50]
