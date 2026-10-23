"""
ОСАГО в аналитике (этап 5): где ОСАГО должно появиться.

Разделы «без ОСАГО» проверяет test_portfolio_regression (весь слепок не
меняется от полиса ОСАГО). Здесь — разделы «с ОСАГО» по решению владельца:
на главной — разрезы структуры по премии, просрочки и радар продлений.
Переключатель ОСАГО в аналитике проверяет test_analytics_v2_framework.
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
