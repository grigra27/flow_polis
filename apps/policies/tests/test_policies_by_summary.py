import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from pytest_django.asserts import assertContains
from django.urls import reverse
from django.utils import timezone

from apps.policies.models import FlowPolicySource
from apps.policies.flow_api import statuses


@pytest.fixture
def group(db):
    return FlowPolicySource.objects.create(summary_id=437, mode="separate", total=8)


@pytest.fixture
def link_policy(
    policy_factory,
    sample_client,
    sample_insurer,
    branch_factory,
    insurance_type_factory,
):
    branch = branch_factory()
    kind = insurance_type_factory()

    def add(source, slot, number, dfa, **kwargs):
        policy = policy_factory(
            policy_number=number,
            dfa_number=dfa,
            client=sample_client,
            insurer=sample_insurer,
            branch=branch,
            insurance_type=kind,
            **kwargs,
        )
        source.links.create(
            slot=slot, policy=policy, revision="r", created_from_summary=False
        )
        return policy

    return add


@pytest.fixture
def reader(client, django_user_model):
    user = django_user_model.objects.create_user("portfolio_reader")
    client.force_login(user)
    return client


def test_portfolio_and_api_agree_on_force_dates_and_exact_summary(
    group, link_policy, reader
):
    today = timezone.localdate()
    past, future = today - timedelta(days=1), today + timedelta(days=1)
    current = link_policy(group, 2, "ACTIVE", "DFA-2", start_date=today, end_date=today)
    ending = link_policy(
        group,
        1,
        "FUTURE-TERMINATION",
        "DFA-1",
        start_date=past,
        end_date=future,
        policy_active=False,
        termination_date=future,
    )
    link_policy(group, 3, "FUTURE-POLICY", "DFA-3", start_date=future, end_date=future)
    link_policy(group, 4, "EXPIRED", "DFA-3", start_date=past, end_date=past)
    link_policy(
        group,
        5,
        "TERMINATED",
        "DFA-2",
        start_date=past,
        end_date=future,
        termination_date=today,
    )
    link_policy(
        group,
        6,
        "MANUAL-CLOSE",
        "DFA-1",
        start_date=past,
        end_date=future,
        policy_active=False,
    )
    other = FlowPolicySource.objects.create(summary_id=438, mode="common", total=1)
    link_policy(
        other, 0, "OTHER-SUMMARY", current.dfa_number, start_date=today, end_date=future
    )
    url = reverse("policies:by-summary", args=[group.pk])
    all_records = reader.get(url)
    assert all_records.status_code == 200
    assert [row.slot for row in all_records.context["links"]] == [1, 2, 3, 4, 5, 6]
    assert "OTHER-SUMMARY" not in all_records.content.decode()
    active = reader.get(url, {"in_force": "1"})
    assert [row.policy_id for row in active.context["links"]] == [ending.pk, current.pk]
    assert active.context["total_links"] == 6
    assert "DFA-1" in active.content.decode() and "DFA-2" in active.content.decode()
    for link in (ending, current):
        origin = {"from_summary": str(group.pk), "in_force": "1"}
        detail_url = reverse("policies:detail", args=[link.pk])
        assert (
            reader.get(detail_url, origin).context["group_url"] == url + "?in_force=1"
        )
        assert (
            reader.get(detail_url, {"from_summary": str(group.pk)}).context["group_url"]
            == url
        )
        assert not reader.get(detail_url, {"from_summary": str(other.pk)}).context.get(
            "group_url"
        )
    assert [row["in_force"] for row in statuses([group.pk])[group.pk]["links"]] == [
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_common_policy_and_empty_active_view(group, link_policy, reader):
    today = timezone.localdate()
    group.mode = "common"
    group.save(update_fields=["mode"])
    link_policy(group, 0, "GROUP-POLICY", "DFA-8", start_date=today + timedelta(days=1))
    url = reverse("policies:by-summary", args=[group.pk])
    full = reader.get(url)
    assert "Все 8" in full.content.decode()
    active = reader.get(url, {"in_force": "1"})
    assert active.status_code == 200 and not active.context["links"]
    assert "Все связанные полисы (1)" in active.content.decode()
    assert "GROUP-POLICY" not in active.content.decode()


@pytest.mark.parametrize("suffix", ["", "?in_force=1"])
def test_login_returns_reader_to_requested_summary(
    client, django_user_model, group, suffix
):
    password = secrets.token_urlsafe(24)
    user = django_user_model.objects.create_user("reader", password=password)
    url = reverse("policies:by-summary", args=[group.pk]) + suffix
    redirect = client.get(url)
    assert parse_qs(urlsplit(redirect.url).query)["next"] == [url]
    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": password, "next": url},
        follow=True,
    )
    assert response.redirect_chain == [(url, 302)] and response.status_code == 200
    assert "По этому своду пока нет связанных полисов" in response.content.decode()


def test_origin_panel_lists_each_real_source_once_and_is_hidden_without_links(
    reader, group, sample_policy, policy_factory, settings
):
    settings.FLOW_ZS_BASE_URL = "https://zs.example"
    url = reverse("policies:detail", args=[sample_policy.pk])
    unlinked = reader.get(url).content.decode()
    assert 'id="flow-source-brand"' not in unlinked
    assert "policy-overview--linked" not in unlinked
    second = FlowPolicySource.objects.create(summary_id=438, mode="common", total=5)
    first_link = group.links.create(
        slot=7, policy=sample_policy, revision="r", created_from_summary=True
    )
    second_link = second.links.create(
        slot=0, policy=sample_policy, revision="r", created_from_summary=False
    )
    content = reader.get(url).content.decode()
    assert "policy-overview--linked" in content
    assert (
        content.index('id="statuses-title"')
        < content.index('id="flow-source-brand"')
        < content.index('id="schedule-title"')
        < content.index('id="info-title"')
        < content.index('id="finance-title"')
    )
    assert (
        content.count(first_link.source_url)
        == content.count(second_link.source_url)
        == 1
    )
    assert "Объект 7 из 8" in content and "Общий полис" in content
    assert "flow-source-card__group-link" not in content

    today = timezone.localdate()
    future = today + timedelta(days=1)
    past = today - timedelta(days=1)
    for slot, number, date in [(2, "TOMORROW", future), (3, "EXPIRED", past)]:
        sibling = policy_factory(
            policy_number=number,
            client=sample_policy.client,
            insurer=sample_policy.insurer,
            branch=sample_policy.branch,
            insurance_type=sample_policy.insurance_type,
            start_date=date,
            end_date=date,
        )
        group.links.create(
            slot=slot, policy=sibling, revision="r", created_from_summary=True
        )
    # Open the policy directly, without the group list's navigation parameters.
    detail = reader.get(url)
    assert detail.status_code == 200
    group_url = reverse("policies:by-summary", args=[group.pk])
    assertContains(detail, 'class="flow-source-card__group-link"', count=1)
    assertContains(detail, f'href="{group_url}"', count=1)
    assertContains(detail, "Полисы этой группы (3)", count=1)
    assert (
        reverse("policies:by-summary", args=[second.pk]) not in detail.content.decode()
    )
