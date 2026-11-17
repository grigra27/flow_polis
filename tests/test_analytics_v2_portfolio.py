"""
Аналитика 2.0, этап 3: «Портфель и удержание» и «Продажи»
(docs/analytics-2.0-plan.md, §3.2, §4 C–D).
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from io import BytesIO
from urllib.parse import urlencode

import pytest
from django.http import QueryDict
from django.urls import reverse
from openpyxl import load_workbook

from apps.analytics import drilldown, money, portfolio
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
    rows = portfolio.retention_by_quarter(
        Policy.objects.all(), date(2026, 7, 1), date(2026, 9, 30), TODAY
    )
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


# --- фактические границы квартальных строк ---------------------------------------


@pytest.fixture
def superuser_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser("p", "p@p.ru", "x"))
    return client


def unpaid(policy, due, kv):
    """Неоплаченный взнос после события — источник потерянной КВ."""
    return PaymentSchedule.objects.create(
        policy=policy,
        year_number=1,
        installment_number=2,
        due_date=due,
        insurance_sum=Decimal("1000000"),
        amount=Decimal(kv) * 4,
        kv_rub=Decimal(kv),
    )


def churn_policy(make, dfa, *, closed_on=None, termination=None):
    """Полис оттока: первый взнос оплачен, теряется только следующий за ним."""
    policy = make(
        date(2025, 1, 1),
        date(2027, 12, 31),
        dfa=dfa,
        kv=1,
        dfa_active=closed_on is None,
        dfa_closed_on=closed_on,
        termination=termination,
    )
    PaymentSchedule.objects.filter(policy=policy, installment_number=1).update(
        paid_date=policy.start_date
    )
    return policy


def list_url(p, key, **opts):
    query = "&".join(part for part in (p.querystring(), urlencode(opts)) if part)
    return reverse("analytics:list", args=[key]) + ("?" + query if query else "")


def excel_numbers(response):
    sheet = load_workbook(BytesIO(response.content)).active
    return [row[0] for row in sheet.iter_rows(min_row=5, values_only=True) if row[0]]


def excel_subtitle(response):
    return load_workbook(BytesIO(response.content)).active.cell(row=2, column=1).value


def test_quarter_window_is_intersection_of_quarter_period_and_today():
    assert portfolio.quarter_window(
        date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 15), TODAY
    ) == (date(2026, 8, 1), date(2026, 9, 15))
    assert portfolio.quarter_window(
        date(2026, 7, 1), date(2026, 7, 1), date(2026, 12, 31), date(2026, 8, 20)
    ) == (date(2026, 7, 1), date(2026, 8, 20))
    assert (
        portfolio.quarter_window(
            date(2026, 7, 1), date(2026, 10, 1), date(2026, 12, 31), TODAY
        )
        is None
    )


def test_partial_quarter_control_example(superuser_client, make):
    """01.08–15.09.2026: из событий 25.07 / 25.08 / 25.09 в отбор входит только 25.08."""
    p = params("from=2026-08-01&to=2026-09-15")
    make(date(2025, 7, 25), date(2026, 7, 25), dfa="J-1")
    august = make(date(2025, 8, 25), date(2026, 8, 25), dfa="A-1")
    make(date(2026, 8, 26), date(2027, 8, 25), dfa="A-1")  # преемник того же СК
    make(date(2025, 9, 25), date(2026, 9, 25), dfa="S-1")

    buyouts, terminations = {}, {}
    for label, closed, kv in (
        ("july", date(2026, 7, 25), 100),
        ("august", date(2026, 8, 25), 300),
        ("september", date(2026, 9, 25), 200),
    ):
        buyouts[label] = unpaid(
            churn_policy(make, f"B-{label}", closed_on=closed), date(2026, 10, 1), kv
        ).policy
    for label, day, kv in (
        ("july", date(2026, 7, 20), 70),
        ("august", date(2026, 8, 20), 50),
        ("september", date(2026, 9, 20), 90),
    ):
        terminations[label] = unpaid(
            churn_policy(make, f"T-{label}", termination=day), date(2026, 10, 1), kv
        ).policy

    data = portfolio_tab.build(p)
    assert [r["code"] for r in data["retention"]] == ["2026Q3"]
    q3 = data["retention"][0]
    assert (q3["label"], q3["start"], q3["end"]) == (
        "III кв. 2026",
        date(2026, 8, 1),
        date(2026, 9, 15),
    )
    assert (q3["due"], q3["renewed"], q3["switched"], q3["not_renewed"]) == (1, 1, 0, 0)
    assert [r["code"] for r in data["churn"]] == ["2026Q3"]
    churn = data["churn"][0]
    assert (churn["early"], churn["terminated"]) == (1, 1)
    assert (churn["early_kv"], churn["terminated_kv"]) == (Decimal(300), Decimal(50))

    august_buyout = buyouts["august"].policy_number
    august_termination = terminations["august"].policy_number
    cases = [
        ("renewal_due", {}, [august.policy_number], q3["due"]),
        ("renewal_due", {"status": "renewed"}, [august.policy_number], q3["renewed"]),
        ("renewal_due", {"status": "switched"}, [], q3["switched"]),
        ("renewal_due", {"status": "not_renewed"}, [], q3["not_renewed"]),
        ("churn", {"reason": "early_buyout"}, [august_buyout], churn["early"]),
        ("churn", {"reason": "termination"}, [august_termination], churn["terminated"]),
        (
            "churn",
            {},
            [august_buyout, august_termination],
            churn["early"] + churn["terminated"],
        ),
    ]
    for key, opts, expected, table_value in cases:
        opts = {"quarter": "2026Q3", **opts}
        assert len(expected) == table_value, (key, opts)
        queryset = drilldown.resolve(key, p, opts)
        assert sorted(queryset.values_list("policy_number", flat=True)) == sorted(
            expected
        ), (key, opts)
        url = list_url(p, key, **opts)
        page = superuser_client.get(url)
        assert page.status_code == 200
        assert page.context["totals"]["count"] == table_value, (key, opts)
        assert page.context["selection_label"] == "01.08.2026 – 15.09.2026"
        assert (
            "Фактические границы отбора: 01.08.2026 – 15.09.2026"
            in page.content.decode()
        )
        export = superuser_client.get(url + "&format=xlsx")
        assert sorted(excel_numbers(export)) == sorted(expected), (key, opts)
        assert "отбор 01.08.2026 – 15.09.2026" in excel_subtitle(export)

    # КВ таблицы — по тем же полисам и тем же границам, что и расшифровка.
    for reason, field in (
        (money.LOSS_EARLY_BUYOUT, "early_kv"),
        (money.LOSS_TERMINATION, "terminated_kv"),
    ):
        queryset = drilldown.resolve(
            "churn", p, {"quarter": "2026Q3", "reason": reason}
        )
        losses = money.lost_in_period(
            money.lost_rows(p.payments().filter(policy__in=queryset)),
            date(2026, 8, 1),
            date(2026, 9, 15),
        )
        assert money.sum_rows(losses)["commission"] == churn[field]


def test_selection_label_follows_quarter_when_period_is_wider(superuser_client, make):
    """Период 01.08–15.10 шире III квартала: отбор и подпись — 01.08–30.09."""
    p = params("from=2026-08-01&to=2026-10-15")
    september = make(date(2025, 9, 20), date(2026, 9, 20), dfa="SEP-1")
    october = make(date(2025, 10, 5), date(2026, 10, 5), dfa="OCT-1")
    sept_buyout = churn_policy(make, "B-SEP", closed_on=date(2026, 9, 20))
    sept_termination = churn_policy(make, "T-SEP", termination=date(2026, 9, 20))
    churn_policy(make, "B-OCT", closed_on=date(2026, 10, 5))
    churn_policy(make, "T-OCT", termination=date(2026, 10, 5))

    # Октябрьские записи существуют: без кода квартала они попадают в отбор.
    wider = superuser_client.get(list_url(p, "renewal_due"))
    assert october.policy_number in [r["cells"][0] for r in wider.context["rows"]]

    cases = [
        ("renewal_due", {}, [september.policy_number]),
        ("churn", {"reason": "early_buyout"}, [sept_buyout.policy_number]),
        ("churn", {"reason": "termination"}, [sept_termination.policy_number]),
        (
            "churn",
            {},
            [sept_buyout.policy_number, sept_termination.policy_number],
        ),
    ]
    for key, opts, expected in cases:
        opts = {"quarter": "2026Q3", **opts}
        url = list_url(p, key, **opts)
        page = superuser_client.get(url)
        assert page.status_code == 200
        assert page.context["totals"]["count"] == len(expected), (key, opts)
        assert sorted(r["cells"][0] for r in page.context["rows"]) == sorted(
            expected
        ), (key, opts)
        assert page.context["selection_label"] == "01.08.2026 – 30.09.2026", (key, opts)
        assert (
            "Фактические границы отбора: 01.08.2026 – 30.09.2026"
            in page.content.decode()
        ), (key, opts)
        export = superuser_client.get(url + "&format=xlsx")
        assert sorted(excel_numbers(export)) == sorted(expected), (key, opts)
        subtitle = excel_subtitle(export)
        assert "отбор 01.08.2026 – 30.09.2026" in subtitle, (key, opts)
        # Общий пользовательский период остаётся в подзаголовке отдельно.
        assert "Период: 01.08.2026 – 15.10.2026" in subtitle, (key, opts)


def test_quarter_rows_keep_events_on_their_actual_edges(make):
    """Период через границу кварталов и после сегодня: события на краях окна."""
    p = params("from=2026-06-15&to=2026-12-31")
    edges = {
        "2026Q2": [date(2026, 6, 15), date(2026, 6, 30)],
        "2026Q3": [date(2026, 7, 1), date(2026, 9, 30)],
        "2026Q4": [date(2026, 10, 1), date(2026, 10, 16)],
    }
    policies = {}
    for days in edges.values():
        for day in days:
            policies[day] = make(
                day - timedelta(days=365), day, dfa=f"E-{day.isoformat()}"
            )
    for day in (date(2026, 6, 14), date(2026, 10, 17), date(2026, 12, 31)):
        make(day - timedelta(days=365), day, dfa=f"X-{day.isoformat()}")

    data = portfolio_tab.build(p)
    assert [r["code"] for r in data["retention"]] == list(edges)
    seen = []
    for row in data["retention"]:
        days = edges[row["code"]]
        assert (row["start"], row["end"]) == (days[0], days[-1])
        assert row["label"] == portfolio.quarter_label(portfolio.quarter_start(days[0]))
        assert row["due"] == len(days)
        numbers = sorted(
            drilldown.resolve("renewal_due", p, {"quarter": row["code"]}).values_list(
                "policy_number", flat=True
            )
        )
        assert numbers == sorted(policies[day].policy_number for day in days)
        seen.extend(numbers)
    assert len(seen) == len(set(seen)) == 6


def test_churn_rows_keep_events_on_their_actual_edges(make):
    p = params("from=2026-06-15&to=2026-12-31")
    edges = {
        "2026Q2": [date(2026, 6, 15), date(2026, 6, 30)],
        "2026Q3": [date(2026, 7, 1), date(2026, 9, 30)],
        "2026Q4": [date(2026, 10, 1), date(2026, 10, 16)],
    }
    days = [day for pair in edges.values() for day in pair]
    outside = [date(2026, 6, 14), date(2026, 10, 17)]
    for day in days + outside:
        buyout = churn_policy(make, f"CB-{day.isoformat()}", closed_on=day)
        unpaid(buyout, date(2027, 1, 1), 10)
        terminated = churn_policy(make, f"CT-{day.isoformat()}", termination=day)
        unpaid(terminated, date(2027, 1, 1), 5)

    rows = {r["code"]: r for r in portfolio_tab.build(p)["churn"]}
    assert set(rows) == set(edges)
    for code, pair in edges.items():
        assert (rows[code]["start"], rows[code]["end"]) == (pair[0], pair[-1])
        assert (rows[code]["early"], rows[code]["terminated"]) == (2, 2)
        assert (rows[code]["early_kv"], rows[code]["terminated_kv"]) == (20, 10)
        for reason, expected in (("early_buyout", 2), ("termination", 2)):
            assert (
                drilldown.resolve(
                    "churn", p, {"quarter": code, "reason": reason}
                ).count()
                == expected
            )


def test_full_quarter_numbers_do_not_depend_on_period_preset(renewals):
    wide = portfolio_tab.build(params())
    exact = portfolio_tab.build(params("from=2026-07-01&to=2026-09-30"))
    keys = (
        "due",
        "renewed",
        "switched",
        "not_renewed",
        "rate",
        "start",
        "end",
        "label",
    )
    q3_wide = next(r for r in wide["retention"] if r["code"] == "2026Q3")
    q3_exact = next(r for r in exact["retention"] if r["code"] == "2026Q3")
    assert {k: q3_wide[k] for k in keys} == {k: q3_exact[k] for k in keys}
    assert (q3_exact["start"], q3_exact["end"]) == (date(2026, 7, 1), date(2026, 9, 30))
    assert (q3_exact["due"], q3_exact["renewed"], q3_exact["switched"]) == (4, 2, 1)
    churn_wide = next(r for r in wide["churn"] if r["code"] == "2026Q3")
    churn_exact = next(r for r in exact["churn"] if r["code"] == "2026Q3")
    assert churn_wide == churn_exact


def test_filters_survive_table_list_and_excel(superuser_client, make, refs):
    august = make(date(2025, 8, 25), date(2026, 8, 25), dfa="F-A")
    make(date(2025, 9, 1), date(2026, 9, 1), dfa="F-B", insurer="b")
    p = params(f"from=2026-08-01&to=2026-09-15&insurer={refs['a'].pk}")
    tab = superuser_client.get(reverse("analytics:portfolio") + "?" + p.querystring())
    assert tab.status_code == 200
    q3 = next(r for r in tab.context["data"]["retention"] if r["code"] == "2026Q3")
    assert q3["due"] == 1  # полис другой СК отсечён фильтром

    found = re.search(
        r'href="(/analytics/list/renewal_due/\?[^"]+)"', tab.content.decode()
    )
    assert found, "В таблице нет ссылки на расшифровку"
    href = unescape(found.group(1))
    assert f"insurer={refs['a'].pk}" in href
    assert "from=2026-08-01" in href and "to=2026-09-15" in href
    assert "quarter=2026Q3" in href

    page = superuser_client.get(href)
    assert page.context["totals"]["count"] == q3["due"]
    assert [row["cells"][0] for row in page.context["rows"]] == [august.policy_number]
    export = superuser_client.get(href + "&format=xlsx")
    assert excel_numbers(export) == [august.policy_number]
    subtitle = excel_subtitle(export)
    assert "Период: 01.08.2026 – 15.09.2026" in subtitle
    assert "отбор 01.08.2026 – 15.09.2026" in subtitle


def test_empty_intersection_gives_no_rows(make):
    make(date(2025, 8, 25), date(2026, 8, 25), dfa="EMPTY")
    p = params("from=2026-10-20&to=2026-12-31")  # целиком после сегодня
    data = portfolio_tab.build(p)
    assert data["retention"] == [] and data["churn"] == []
    assert drilldown.resolve("renewal_due", p, {"quarter": "2026Q3"}).count() == 0
    assert drilldown.resolve("churn", p, {"quarter": "2026Q3"}).count() == 0
