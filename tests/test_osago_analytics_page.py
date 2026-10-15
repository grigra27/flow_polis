"""Страница «Аналитика ОСАГО» (этап 6)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.analytics.osago import build_osago_analytics
from tests.test_portfolio_regression import add_osago_policy, portfolio  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_totals_and_breakdowns(portfolio):  # noqa: F811
    policy = add_osago_policy(portfolio)
    data = build_osago_analytics(year=policy.start_date.year)

    totals = data["totals"]
    assert totals["policies"] == 1
    assert totals["in_force"] == 1
    assert totals["premium"] == Decimal("15000")
    assert totals["kv"] == Decimal("1500")
    assert totals["kv_percent"] == Decimal("10")
    assert totals["paid"] == 1

    assert [r["name"] for r in data["by_insurer"]] == ["СК Альфа"]
    assert [r["name"] for r in data["by_branch"]] == ["Москва"]
    assert [r["name"] for r in data["by_client"]] == ["ООО Первый"]
    month = data["by_month"][policy.start_date.month - 1]
    assert (month["policies"], month["premium"]) == (1, Decimal("15000"))
    assert sum(m["policies"] for m in data["by_month"]) == 1


def test_non_osago_policies_are_ignored(portfolio):  # noqa: F811
    data = build_osago_analytics(year=date.today().year)

    assert data["totals"]["policies"] == 0
    assert data["totals"]["premium"] == Decimal("0")
    assert data["by_insurer"] == []


def test_year_filter(portfolio):  # noqa: F811
    policy = add_osago_policy(portfolio)
    other_year = policy.start_date.year - 1

    assert build_osago_analytics(year=other_year)["totals"]["policies"] == 0
    assert policy.start_date.year in build_osago_analytics()["years"]


def test_page_for_superuser(client, django_user_model, portfolio):  # noqa: F811
    add_osago_policy(portfolio)
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    response = client.get(reverse("analytics:osago_analytics"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Аналитика ОСАГО" in html
    assert "СК Альфа" in html
    assert "15 000 ₽" in html


def test_bad_year_falls_back(client, django_user_model, db):
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    response = client.get(reverse("analytics:osago_analytics"), {"year": "abc"})

    assert response.status_code == 200
    assert response.context["year"] == date.today().year


def test_page_is_superuser_only(client, django_user_model, db):
    client.force_login(
        django_user_model.objects.create_user("s", password="x", is_staff=True)
    )

    response = client.get(reverse("analytics:osago_analytics"))

    assert response.status_code == 302
