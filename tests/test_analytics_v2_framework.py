"""
Аналитика 2.0, этап 1: каркас — параметры фильтров, базовые выборки,
вкладки и список «под цифрой» с выгрузкой (docs/analytics-2.0-plan.md).
"""

from datetime import date

import pytest
from django.http import QueryDict
from django.urls import reverse

from apps.analytics import drilldown
from apps.analytics.filters import AnalyticsParams
from apps.analytics.views_v2 import TAB_KEYS
from tests.test_portfolio_regression import add_osago_policy, portfolio  # noqa: F401

TODAY = date(2026, 10, 16)


def params(query="", today=TODAY):
    return AnalyticsParams.from_query(QueryDict(query), today=today)


# --- параметры -------------------------------------------------------------


@pytest.mark.unit
def test_default_period_is_current_year():
    p = params()
    assert (p.date_from, p.date_to, p.preset) == (
        date(2026, 1, 1),
        date(2026, 12, 31),
        "year",
    )
    assert p.as_of == TODAY
    assert not p.with_osago


@pytest.mark.unit
@pytest.mark.parametrize(
    "preset, start, end",
    [
        ("prev_year", date(2025, 1, 1), date(2025, 12, 31)),
        ("quarter", date(2026, 10, 1), date(2026, 12, 31)),
        ("month", date(2026, 10, 1), date(2026, 10, 31)),
        ("12m", date(2025, 11, 1), date(2026, 10, 31)),
    ],
)
def test_period_presets(preset, start, end):
    p = params(f"period={preset}")
    assert (p.date_from, p.date_to, p.preset) == (start, end, preset)


@pytest.mark.unit
def test_explicit_dates_win_and_are_ordered():
    p = params("period=month&from=2026-06-30&to=2026-03-01")
    assert (p.date_from, p.date_to, p.preset) == (
        date(2026, 3, 1),
        date(2026, 6, 30),
        None,
    )


@pytest.mark.unit
def test_bad_values_are_ignored():
    p = params("period=nonsense&branch=1&branch=x&branch=1&insurer=&as_of=bad")
    assert p.preset == "year"
    assert p.branch == [1]
    assert p.insurer == []
    assert p.as_of == TODAY


@pytest.mark.unit
def test_querystring_round_trip():
    query = "period=quarter&branch=3&branch=1&type=2&manager=5&osago=1&as_of=2026-09-30"
    p = params(query)
    again = params(p.querystring())
    assert again == p
    # Год по умолчанию в ссылку не пишется.
    assert params().querystring() == ""


@pytest.mark.unit
def test_preset_links_keep_dimensions():
    links = {link["key"]: link for link in params("insurer=7").preset_links()}
    assert links["year"]["active"]
    assert "insurer=7" in links["month"]["query"]
    assert "period=month" in links["month"]["query"]


# --- базовые выборки -------------------------------------------------------


@pytest.mark.django_db
def test_base_querysets_exclude_osago_and_non_broker(portfolio):  # noqa: F811
    from apps.policies.models import Policy

    add_osago_policy(portfolio)
    Policy.objects.filter(policy_number="P2").update(broker_participation=False)

    p = params(today=portfolio["today"])
    assert set(p.policies().values_list("policy_number", flat=True)) == {
        "P1",
        "P3",
        "P4",
    }
    assert set(p.non_broker_policies().values_list("policy_number", flat=True)) == {
        "P2"
    }
    assert p.payments().count() == 6  # P1 ×4, P3, P4

    with_osago = params("osago=1", today=portfolio["today"])
    assert "OSAGO-R1" in with_osago.policies().values_list("policy_number", flat=True)


@pytest.mark.django_db
def test_dimension_filters(portfolio):  # noqa: F811
    insurer_a = portfolio["insurers"][0]
    p = params(f"insurer={insurer_a.pk}", today=portfolio["today"])
    assert set(p.policies().values_list("policy_number", flat=True)) == {"P1", "P3"}
    assert set(p.payments().values_list("policy__insurer", flat=True)) == {insurer_a.pk}


# --- страницы --------------------------------------------------------------


@pytest.fixture
def superuser_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))
    return client


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize("tab", TAB_KEYS)
def test_tabs_render(superuser_client, portfolio, tab):  # noqa: F811
    add_osago_policy(portfolio)
    url = reverse(f"analytics:v2_{tab}")
    assert superuser_client.get(url).status_code == 200
    assert superuser_client.get(url + "?period=prev_year&osago=1").status_code == 200


@pytest.mark.integration
@pytest.mark.django_db
def test_tabs_are_superuser_only(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("u", "u@u.ru", "x"))
    response = client.get(reverse("analytics:v2_summary"))
    assert response.status_code == 302
    assert "access" in response["Location"]


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize("key", ["payments_due", "in_force", "non_broker"])
def test_drilldown_list_and_excel(superuser_client, portfolio, key):  # noqa: F811
    url = reverse("analytics:v2_list", args=[key])
    response = superuser_client.get(url)
    assert response.status_code == 200

    export = superuser_client.get(url + "?format=xlsx")
    assert export.status_code == 200
    assert export["Content-Type"].startswith("application/vnd.openxmlformats")


@pytest.mark.integration
@pytest.mark.django_db
def test_drilldown_numbers_match_queryset(superuser_client, portfolio):  # noqa: F811
    p = params(today=portfolio["today"])
    expected = drilldown.resolve("in_force", p).count()
    response = superuser_client.get(reverse("analytics:v2_list", args=["in_force"]))
    assert response.context["totals"]["count"] == expected
    assert len(response.context["rows"]) == expected


@pytest.mark.integration
@pytest.mark.django_db
def test_unknown_metric_is_404(superuser_client):
    response = superuser_client.get(reverse("analytics:v2_list", args=["nope"]))
    assert response.status_code == 404
