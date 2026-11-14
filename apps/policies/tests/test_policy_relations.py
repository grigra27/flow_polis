from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.policies.services.policy_relations import coverage_status

pytestmark = pytest.mark.django_db


def test_dfa_group_requires_full_number_and_same_client(
    client, django_user_model, policy_factory
):
    client.force_login(django_user_model.objects.create_user("reader"))
    source = policy_factory(dfa_number=" СПБ-0012-3 ")
    match = policy_factory(
        client=source.client,
        insurance_type=source.insurance_type,
        dfa_number="спб – 0012 - 3",
        vin_number="DIFFERENTVIN",
    )
    for number in ("СПБ-0012-4", "СПБ-0012", "0012-3", "СПБ-12-3", ""):
        policy_factory(
            client=source.client,
            insurance_type=source.insurance_type,
            dfa_number=number,
        )
    policy_factory(insurance_type=source.insurance_type, dfa_number=source.dfa_number)
    response = client.get(reverse("policies:detail", args=[source.pk]))
    assert response.status_code == 200
    assert [x["policy"] for x in response.context["dfa_policies"]] == [match]
    assert reverse("policies:detail", args=[match.pk]) in response.content.decode()
    assert "Ещё 1 полис по ДФА" in response.content.decode()


@pytest.mark.parametrize("number", ["", "  ", "Предварительный"])
def test_missing_or_provisional_dfa_never_links_unrelated_records(
    admin_client, policy_factory, number
):
    source = policy_factory(dfa_number=number)
    policy_factory(
        client=source.client, insurance_type=source.insurance_type, dfa_number=number
    )
    response = admin_client.get(reverse("policies:detail", args=[source.pk]))
    assert response.context["dfa_policies"] == []
    assert 'id="dfa-policies"' not in response.content.decode()


def test_vin_history_orders_by_type_and_dates_and_preserves_changed_lessee(
    admin_client, policy_factory, insurance_type_factory
):
    today = timezone.localdate()
    source = policy_factory(
        vin_number="HISTORY001",
        start_date=today - timedelta(days=365),
        end_date=today - timedelta(days=1),
    )
    successor = policy_factory(
        vin_number=source.vin_number,
        insurance_type=source.insurance_type,
        start_date=today,
        end_date=today + timedelta(days=364),
    )
    future = policy_factory(
        vin_number=source.vin_number,
        insurance_type=source.insurance_type,
        start_date=today + timedelta(days=365),
        end_date=today + timedelta(days=729),
    )
    osago = policy_factory(
        vin_number=source.vin_number,
        insurance_type=insurance_type_factory(name="ОСАГО", is_osago=True),
        franchise=0,
    )
    response = admin_client.get(reverse("policies:detail", args=[source.pk]))
    groups = response.context["vin_history"]
    history = next(
        g["contracts"] for g in groups if g["insurance_type"] == source.insurance_type
    )
    assert [item["policy"] for item in history] == [source, successor, future]
    assert [item["status"] for item in history] == ["completed", "current", "upcoming"]
    assert [item["policy"] for item in history if item["is_next"]] == [successor]
    assert history[0]["is_open_card"]
    assert history[1]["different_client"]
    assert len(groups) == 2
    html = response.content.decode()
    assert "Следующий договор в базе" in html
    assert successor.client.client_name in html
    assert reverse("policies:detail", args=[osago.pk]) in html
    assert "?role=lessee" in html


@pytest.mark.parametrize(
    "start,end,active,termination,expected",
    [
        (-10, 10, True, None, "current"),
        (-10, 10, False, 5, "current"),
        (1, 10, False, 5, "upcoming"),
        (-10, -1, True, None, "completed"),
        (-10, 10, True, 0, "terminated"),
        (-10, 10, False, None, "terminated"),
    ],
)
def test_coverage_status_matches_dates_including_planned_termination(
    policy_factory, start, end, active, termination, expected
):
    today = timezone.localdate()
    policy = policy_factory(
        start_date=today + timedelta(days=start),
        end_date=today + timedelta(days=end),
        policy_active=active,
        termination_date=today + timedelta(days=termination)
        if termination is not None
        else None,
    )
    assert coverage_status(policy, today)[0] == expected


def test_company_links_open_the_corresponding_role(
    admin_client, policy_factory, client_factory
):
    source = policy_factory(policyholder=client_factory())
    html = admin_client.get(
        reverse("policies:detail", args=[source.pk])
    ).content.decode()
    for company_id, role in (
        (source.client_id, "lessee"),
        (source.policyholder_id, "policyholder"),
    ):
        url = reverse("clients:detail", args=[company_id], query={"role": role})
        assert f'href="{url}"' in html
        destination = admin_client.get(url)
        assert source in destination.context["policies"]


def test_next_contract_in_history_does_not_skip_a_later_terminated_contract(
    admin_client, policy_factory
):
    today = timezone.localdate()
    source = policy_factory(
        vin_number="HISTORY001",
        start_date=today - timedelta(days=90),
        end_date=today - timedelta(days=61),
    )
    terminated = policy_factory(
        insurance_type=source.insurance_type,
        vin_number=source.vin_number,
        start_date=today - timedelta(days=60),
        end_date=today - timedelta(days=31),
        termination_date=today - timedelta(days=45),
        policy_active=False,
    )
    policy_factory(
        insurance_type=source.insurance_type,
        vin_number=source.vin_number,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=30),
    )
    response = admin_client.get(reverse("policies:detail", args=[source.pk]))
    history = response.context["vin_history"][0]["contracts"]
    following = [item for item in history if item["is_next"]]
    assert len(following) == 1
    assert following[0]["policy"] == terminated
    assert following[0]["status"] == "terminated"
