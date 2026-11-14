from datetime import date, timedelta
from decimal import Decimal
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy
from apps.core.services.dashboard_v3_service import DashboardV3Service
from apps.core.services.portfolio_scope import PortfolioScope
from apps.reports.services.insured_value import current_insured_sums
from apps.reports.services.property_report import (
    build_property_report,
    build_property_report_workbook,
)
from apps.reports.services.property_snapshot import build_property_snapshot

AS_OF = date(2027, 6, 15)  # Все сервисы получают явную дату, не зависят от часов.
pytestmark = pytest.mark.django_db


@pytest.fixture
def make_policy():
    client = Client.objects.create(
        client_name="Тестовый лизингополучатель", client_inn="7700000991"
    )
    branch = Branch.objects.create(branch_name="Север")
    insurer = Insurer.objects.create(insurer_name="СК Проверка")
    kind = InsuranceType.objects.create(name="Имущество тест", needs_prolongation=True)
    counter = 0

    def make(**changes):
        nonlocal counter
        counter += 1
        fields = dict(
            policy_number=f"D3-{counter}",
            dfa_number=f"DFA-{counter}",
            client=client,
            branch=branch,
            insurer=insurer,
            insurance_type=kind,
            property_description="Оборудование",
            start_date=AS_OF - timedelta(days=500),
            end_date=AS_OF + timedelta(days=200),
            policy_active=True,
            dfa_active=True,
            broker_participation=True,
            policy_uploaded=True,
        )
        fields.update(changes)
        return Policy.objects.create(**fields)

    return make


def pay(policy, *, year=1, installment=1, due=None, value=1000, amount=100, paid=None):
    # Неполные исторические графики и нетипичный порядок оплат тоже должны
    # корректно читаться. bulk_create намеренно обходит валидацию новых записей.
    payment = PaymentSchedule(
        policy=policy,
        year_number=year,
        installment_number=installment,
        due_date=due or AS_OF - timedelta(days=10),
        insurance_sum=None if value is None else Decimal(value),
        amount=Decimal(amount),
        paid_date=paid,
        kv_rub=Decimal("98765.43"),
    )
    PaymentSchedule.objects.bulk_create([payment])
    return payment


def service(scope="all", branches=()):
    return DashboardV3Service(PortfolioScope(AS_OF, scope, branches))


def test_current_year_matches_both_reports_and_is_not_counted_per_installment(
    make_policy,
):
    p = make_policy()
    pay(p, year=1, due=AS_OF - timedelta(days=400), value=1000)
    pay(p, year=2, value=800)
    pay(p, year=2, installment=2, due=AS_OF + timedelta(days=20), value=9999)
    pay(p, year=3, due=AS_OF + timedelta(days=355), value=600)
    context = service().context()
    assert context["total_sum"] == 800
    assert context["total_sum"] == build_property_snapshot(AS_OF)["total_insurance_sum"]
    assert context["total_sum"] == build_property_report(AS_OF)["totals"]["sum"]
    assert context["annual_premium"] == 200
    assert all(
        sum(r["amount"] for r in chart["rows"])
        == (800 if chart["measure"] == "sum" else 200)
        for chart in context["structure"]
    )


def test_missing_current_value_never_uses_previous_maximum(make_policy):
    p = make_policy()
    pay(p, year=1, due=AS_OF - timedelta(days=400), value=1000)
    pay(p, year=2, value=None)
    assert current_insured_sums([p.pk], AS_OF) == {}
    context = service().context()
    assert context["total_sum"] == 0
    assert context["policy_count"] == context["missing_sum_count"] == 1
    report = build_property_report(AS_OF)
    assert report["totals"]["missing_sum_count"] == 1
    assert report["top_objects"][0]["sum"] is None
    assert build_property_report_workbook(report)["Крупнейшие объекты"].max_row > 0


def test_missing_first_installment_is_unknown_even_when_other_values_exist(make_policy):
    p = make_policy()
    pay(p, installment=2, value=5000)
    assert current_insured_sums([p.pk], AS_OF) == {}
    assert service().missing_sum == {p.pk}


def test_missing_first_installment_of_new_year_does_not_restore_old_sum(make_policy):
    p = make_policy()
    pay(p, year=1, due=AS_OF - timedelta(days=400), value=1000)
    pay(p, year=2, installment=2, value=800)
    assert current_insured_sums([p.pk], AS_OF) == {}


@pytest.mark.parametrize(
    "scope, expected", [("all", 300), ("broker", 100), ("direct", 200)]
)
def test_global_scope_applies_to_every_tab_and_reports(make_policy, scope, expected):
    a = make_policy(
        start_date=AS_OF - timedelta(days=10),
        end_date=AS_OF + timedelta(days=15),
        policy_uploaded=False,
    )
    b = make_policy(
        broker_participation=False,
        start_date=AS_OF - timedelta(days=10),
        end_date=AS_OF + timedelta(days=15),
        policy_uploaded=False,
    )
    pay(a, value=100, amount=10)
    pay(b, value=200, amount=20)
    for tab in ("overview", "portfolio", "payments", "quality"):
        context = service(scope).context(tab)
        assert context["total_sum"] == expected
        assert context["annual_premium"] == expected / 10
        assert context["activity"]["windows"][0]["sum"] == expected
        assert context["renewal"][0]["sum"] == expected
        assert context["tasks"][0]["amount"] == expected / 10
        assert context["problems"][1]["count"] == (2 if scope == "all" else 1)
        if tab == "portfolio":
            assert context["property_report"]["totals"]["sum"] == expected
    assert (
        build_property_snapshot(AS_OF, structure_scope=scope)["total_insurance_sum"]
        == expected
    )


def test_branch_filter_also_restricts_worklists_and_activity(make_policy):
    a = make_policy(start_date=AS_OF - timedelta(days=5))
    other = Branch.objects.create(branch_name="Юг")
    b = make_policy(branch=other, start_date=AS_OF - timedelta(days=5))
    pay(a, value=100)
    pay(b, value=900)
    scoped = service(branches=(a.branch_id,))
    context = scoped.context("portfolio")
    assert context["total_sum"] == context["property_report"]["totals"]["sum"] == 100
    assert context["activity"]["windows"][0]["count"] == 1
    assert [row["id"] for row in scoped.detail({"detail": "overdue"})["rows"]] == [a.pk]


def test_prepayment_future_payment_and_aging_reconcile_at_snapshot(make_policy):
    p = make_policy()
    pay(
        p,
        installment=1,
        due=AS_OF - timedelta(days=10),
        amount=10,
        paid=AS_OF + timedelta(days=1),
    )
    pay(
        p,
        installment=2,
        due=AS_OF + timedelta(days=10),
        amount=20,
        paid=AS_OF - timedelta(days=1),
    )
    pay(p, installment=3, due=AS_OF, amount=30)
    pay(p, installment=4, due=AS_OF + timedelta(days=29), amount=40)
    pay(p, installment=5, due=AS_OF + timedelta(days=30), amount=50)
    pay(p, installment=6, due=date(2028, 1, 1), amount=900)
    s = service()
    context = s.context()
    assert [part["amount"] for part in context["bridge"]] == [20, 10, 120]
    assert (
        sum(part["amount"] for part in context["bridge"])
        == context["annual_premium"]
        == 150
    )
    assert sum(p["amount"] for p in s.upcoming) == 70
    assert context["aging"][0]["amount"] == 10
    assert context["paid_recent"]["amount"] == 20


def test_known_future_closure_excludes_obligations_and_renewals(make_policy):
    p = make_policy(
        dfa_deactivation_date=AS_OF + timedelta(days=5),
        end_date=AS_OF + timedelta(days=10),
    )
    pay(p)
    pay(p, installment=2, due=AS_OF + timedelta(days=6), amount=999)
    context = service().context()
    assert context["annual_premium"] == 100
    assert context["renewal"][0]["count"] == 0


def test_historical_dfa_and_policy_membership_are_reconstructed(make_policy):
    p = make_policy(dfa_active=False, dfa_deactivation_date=AS_OF - timedelta(days=10))
    pay(p, due=AS_OF - timedelta(days=100), value=1000)
    context = service().context()
    assert context["total_sum"] == 0
    assert context["flows"][0]["left"] == 1
    assert context["flows"][0]["sum_delta"] == -1000
    report = build_property_snapshot(AS_OF - timedelta(days=30))
    assert report["total_insurance_sum"] == 1000


def test_osago_is_only_in_premium_and_payments(make_policy):
    kind = InsuranceType.objects.create(name="ОСАГО D3", is_osago=True)
    p = make_policy(
        insurance_type=kind, policy_uploaded=False, end_date=AS_OF + timedelta(days=20)
    )
    pay(p, value=None, amount=777)
    context = service().context()
    assert (
        context["policy_count"]
        == context["lessees"]
        == context["missing_sum_count"]
        == 0
    )
    assert context["annual_premium"] == 777
    assert context["problems"][1]["count"] == 0
    assert context["activity"]["score"] is None


def test_commission_is_neither_loaded_nor_used_in_public_context(make_policy):
    p = make_policy(start_date=AS_OF - timedelta(days=10))
    pay(p)
    with CaptureQueriesContext(connection) as queries:
        before = service().context("portfolio")
    sql = " ".join(q["sql"].lower() for q in queries)
    assert "kv_rub" not in sql and "commission_rate" not in sql
    PaymentSchedule.objects.update(kv_rub=Decimal("0"))
    after = service().context("portfolio")
    before.pop("generated_at")
    after.pop("generated_at")
    assert before == after
    data = json.dumps(before, default=str, ensure_ascii=False).lower()
    assert not any(
        word in data for word in ("kv_rub", "commission", "вознагражден", "98765.43")
    )


@pytest.mark.parametrize("superuser", [False, True])
def test_page_keeps_six_charts_no_revenue_and_filters_in_links(
    client, make_policy, superuser
):
    p = make_policy()
    pay(p)
    user = User.objects.create_user(
        username=f"d3-{superuser}", is_superuser=superuser, is_staff=superuser
    )
    client.force_login(user)
    response = client.get(
        reverse("core:dashboard"),
        {
            "tab": "portfolio",
            "as_of": AS_OF.isoformat(),
            "branch": p.branch_id,
            "structure_scope": "broker",
        },
    )
    assert response.status_code == 200
    html = response.content.decode()
    dashboard_html = html.split('<div class="d3"', 1)[1].split("</main>", 1)[0]
    assert dashboard_html.count('class="d3-donut"') == 6
    assert not any(
        word in dashboard_html.lower()
        for word in ("commission", "вознагражден", "98765.43", "доход", "кв ")
    )
    for target in (
        response.context["snapshot_url"],
        response.context["excel_url"],
        response.context["tasks"][0]["url"],
        response.context["tabs"][2]["url"],
    ):
        params = parse_qs(urlsplit(target).query)
        assert params["as_of"] == [AS_OF.isoformat()]
        assert params["structure_scope"] == ["broker"]
        assert params["branch"] == [str(p.branch_id)]
    assert client.get(response.context["snapshot_url"]).status_code == 200
    assert client.get(response.context["excel_url"]).status_code == 200
    detail = client.get(response.context["tasks"][0]["url"])
    assert detail.context["detail"]["total"] == 1


@pytest.mark.parametrize("tab", ["overview", "portfolio", "payments", "quality"])
def test_empty_and_malformed_filters_render_honestly(client, tab):
    user = User.objects.create_user(username="empty-d3")
    client.force_login(user)
    response = client.get(
        reverse("core:dashboard"),
        {
            "tab": tab,
            "as_of": "2027-02-31",
            "structure_scope": "invalid",
            "branch": "9999999999999999999999999",
        },
    )
    assert response.status_code == 200
    assert response.context["policy_count"] == 0
    assert response.context["activity"]["score"] is None
    assert response.context["quality_score"] is None


def test_segment_other_and_pagination_keep_scope(client, make_policy):
    for index in range(7):
        branch = Branch.objects.create(branch_name=f"Филиал {index}")
        pay(make_policy(branch=branch), value=(index + 1) * 100)
    s = service()
    detail = s.detail(
        {
            "detail": "segment",
            "dimension": "branch",
            "measure": "sum",
            "entity": "other",
        }
    )
    assert len(detail["rows"]) == 2
    assert sum(r["amount"] for r in detail["rows"]) == 300
    user = User.objects.create_user(username="pagination-d3")
    client.force_login(user)
    for _ in range(42):
        pay(make_policy())
    response = client.get(
        reverse("core:dashboard"),
        {
            "detail": "policies",
            "as_of": AS_OF.isoformat(),
            "structure_scope": "broker",
            "page": 2,
        },
    )
    assert response.context["detail"]["page"].number == 2
    assert len(response.context["detail"]["page"]) == 9
    assert "structure_scope=broker" in response.context["detail"]["previous_url"]


def test_scope_parser_accepts_legacy_links_and_multiple_branches():
    scope = PortfolioScope.from_query(
        QueryDict(
            "as_of=2027-06-15&structure_scope=broker_only&branch=2&branch=1&branch=1"
        )
    )
    assert scope.structure_scope == "broker"
    assert scope.branch_ids == (1, 2)
