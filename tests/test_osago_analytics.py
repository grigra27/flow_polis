"""
ОСАГО в аналитике (этап 5): где ОСАГО должно появиться.

Разделы «без ОСАГО» проверяет test_portfolio_regression (весь слепок не
меняется от полиса ОСАГО). Здесь — разделы «с ОСАГО» по решению владельца:
финансовая аналитика (премия и КВ), на главной — разрезы структуры по
премии, просрочки и радар продлений.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from tests.test_portfolio_regression import add_osago_policy, portfolio  # noqa: F401

pytestmark = pytest.mark.integration


def _dashboard_v2():
    from apps.core.services.dashboard_v2_service import DashboardV2Service

    cache.clear()
    return DashboardV2Service().get_dashboard_context()


def _add_overdue_osago(portfolio):  # noqa: F811
    """Действующее ОСАГО с неоплаченным платежом 40 дней назад."""
    policy = add_osago_policy(portfolio)
    start = portfolio["today"] - timedelta(days=40)
    policy.start_date = start
    policy.end_date = start + timedelta(days=364)
    policy.save()
    policy.payment_schedule.update(due_date=start, paid_date=None)
    return policy


def test_financial_analytics_includes_osago(portfolio):  # noqa: F811
    from apps.analytics.services import AnalyticsService

    cache.clear()
    before = AnalyticsService().get_financial_analytics()["payment_status_analysis"]
    add_osago_policy(portfolio)
    cache.clear()
    after = AnalyticsService().get_financial_analytics()["payment_status_analysis"]

    assert after["total_payments"] == before["total_payments"] + 1
    assert after["paid_amount"] == before["paid_amount"] + Decimal("15000")


def test_structure_premium_breakdown_includes_osago(portfolio):  # noqa: F811
    add_osago_policy(portfolio)
    structure = _dashboard_v2()["dashboard_v2_structure"]

    premium_types = [row["name"] for row in structure["type_breakdown_premium"]["top"]]
    sum_types = [row["name"] for row in structure["by_type"]]

    assert "ОСАГО (регрессия)" in premium_types
    assert "ОСАГО (регрессия)" not in sum_types


def test_structure_policy_count_excludes_osago(portfolio):  # noqa: F811
    before = _dashboard_v2()["dashboard_v2_structure"]["policy_count"]
    add_osago_policy(portfolio)

    assert _dashboard_v2()["dashboard_v2_structure"]["policy_count"] == before


def test_overdue_aging_includes_osago(portfolio):  # noqa: F811
    before = _dashboard_v2()["dashboard_v2_aging"]
    _add_overdue_osago(portfolio)
    after = _dashboard_v2()["dashboard_v2_aging"]

    assert after["total_count"] == before["total_count"] + 1
    assert after["total_amount"] == before["total_amount"] + Decimal("15000")


def test_renewal_radar_includes_osago(portfolio):  # noqa: F811
    before = _dashboard_v2()["dashboard_v2_renewal"]["active_total"]
    add_osago_policy(portfolio)

    assert _dashboard_v2()["dashboard_v2_renewal"]["active_total"] == before + 1


def test_osago_free_analytics_hide_osago_type_in_filters(client, django_user_model):
    from django.urls import reverse

    from apps.insurers.models import InsuranceType

    InsuranceType.objects.create(name="ОСАГО (фильтр)", is_osago=True)
    InsuranceType.objects.create(name="КАСКО (фильтр)")
    client.force_login(
        django_user_model.objects.create_superuser("root", "r@r.ru", "x")
    )

    for url_name, osago_visible in [
        ("analytics:insurer_analytics", False),
        ("analytics:client_analytics", False),
        ("analytics:financial_analytics", True),
    ]:
        response = client.get(reverse(url_name))
        names = [t.name for t in response.context["insurance_types"]]
        assert "КАСКО (фильтр)" in names, url_name
        assert ("ОСАГО (фильтр)" in names) is osago_visible, url_name
