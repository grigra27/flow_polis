import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_portfolio_reader_returns_to_policy_without_handoff_permissions(
    client, django_user_model, policy_factory, settings
):
    settings.FLOW_HANDOFF_ENABLED = False
    login_password = secrets.token_urlsafe(24)
    reader = django_user_model.objects.create_user("reader", password=login_password)
    policy = policy_factory()
    detail = reverse("policies:detail", args=[policy.pk])
    first = client.get(detail)
    target = parse_qs(urlsplit(first.url).query)["next"][0]
    assert target == detail
    result = client.post(
        reverse("accounts:login"),
        {
            "username": reader.username,
            "password": login_password,
            "next": target,
        },
        follow=True,
    )
    assert result.redirect_chain == [(detail, 302)]
    assert result.status_code == 200
    assert result.context["policy"].pk == policy.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    "target",
    [
        "//example.com/policies/1/",
        "https://example.com/policies/1/",
        "https://testserver/policies/1/",
        "/admin/",
        "/policies/1/?next=untrusted",
        "/policies/by-summary/100/?in_force=1&next=untrusted",
        "/flow/from-zs/?continue=not-in-session",
    ],
)
def test_regular_login_preserves_dashboard_for_other_destinations(
    client, django_user_model, target
):
    login_password = secrets.token_urlsafe(24)
    reader = django_user_model.objects.create_user("reader", password=login_password)
    response = client.post(
        reverse("accounts:login"),
        {
            "username": reader.username,
            "password": login_password,
            "next": target,
        },
    )
    assert response.url == reverse("core:dashboard")
