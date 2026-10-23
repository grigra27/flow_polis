"""Дымовой тест: все страницы открываются, когда в портфеле есть ОСАГО."""

import pytest
from django.urls import reverse

from tests.test_portfolio_regression import add_osago_policy, portfolio  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

PAGES = [
    "core:dashboard",
    "analytics:summary",
    "analytics:money",
    "analytics:sales",
    "analytics:portfolio",
    "analytics:insurers",
    "analytics:channels",
    "analytics:clients",
    "analytics:osago",
    "analytics:data_quality",
    "reports:index",
    "reports:custom_export",
    "reports:property_snapshot_report",
    "policies:list",
    "policies:payments",
    "policies:scheduled_payments",
    "policies:prolongation",
    "admin:policies_policy_changelist",
    "admin:policies_osagopolicy_changelist",
    "admin:policies_paymentschedule_changelist",
    "admin:insurers_insurancetype_changelist",
    "admin:insurers_commissionrate_changelist",
]


@pytest.mark.parametrize("url_name", PAGES)
def test_page_renders_with_osago(
    client, django_user_model, portfolio, url_name
):  # noqa: F811
    policy = add_osago_policy(portfolio)
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    response = client.get(reverse(url_name))

    assert response.status_code == 200, url_name
    if url_name == "admin:policies_osagopolicy_changelist":
        assert policy.policy_number in response.content.decode()


def test_osago_policy_pages(client, django_user_model, portfolio):  # noqa: F811
    policy = add_osago_policy(portfolio)
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    for url in [
        reverse("policies:detail", args=[policy.pk]),
        reverse("admin:policies_osagopolicy_change", args=[policy.pk]),
        reverse("clients:detail", args=[policy.client_id]),
        reverse("insurers:detail", args=[policy.insurer_id]),
        reverse("insurers:branch_detail", args=[policy.branch_id]),
    ]:
        assert client.get(url).status_code == 200, url
