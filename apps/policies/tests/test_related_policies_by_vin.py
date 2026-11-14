from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.insurers.models import InsuranceType

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("is_staff", [False, True])
def test_same_vin_links_work_both_ways_without_creation_permissions(
    client, django_user_model, policy_factory, is_staff
):
    user = django_user_model.objects.create_user("viewer", is_staff=is_staff)
    client.force_login(user)
    contracts = []
    for name, is_osago, vin in (
        ("КАСКО", False, "VINLINK001"),
        ("ОСАГО", True, "vinlink001"),
        ("Спецтехника", False, "VINLINK001"),
    ):
        kind = InsuranceType.objects.create(name=name, is_osago=is_osago)
        contracts.append(
            policy_factory(
                policy_number=name + "-LINK",
                insurance_type=kind,
                vin_number=vin,
                franchise=0,
            )
        )
    unrelated = policy_factory(vin_number="OTHER001")
    for current in contracts:
        response = client.get(reverse("policies:detail", args=[current.pk]))
        assert response.status_code == 200
        expected = {contract.pk for contract in contracts if contract != current}
        assert {
            contract.pk for contract, status in response.context["related_policies"]
        } == expected
        markup = response.content.decode()
        assert "История страхования объекта" in markup
        assert "Оформить ОСАГО на этот объект" not in markup
        for other in contracts:
            if other != current:
                assert (
                    markup.count(
                        'href="' + reverse("policies:detail", args=[other.pk]) + '"'
                    )
                    == 1
                )
                assert other.insurance_type.name in markup
        assert reverse("policies:detail", args=[unrelated.pk]) not in markup


@pytest.mark.parametrize("vin", ["", "   ", "ONLY001"])
def test_empty_vin_or_no_other_contracts_hides_the_related_policies_block(
    admin_client, policy_factory, vin
):
    source = policy_factory(vin_number=vin)
    policy_factory(
        insurance_type=source.insurance_type,
        vin_number=vin if not vin.strip() else "OTHER001",
    )
    response = admin_client.get(reverse("policies:detail", args=[source.pk]))
    assert response.status_code == 200
    assert response.context["related_policies"] == []
    assert "История страхования объекта" not in response.content.decode()


def test_other_contracts_keep_their_coverage_statuses(
    admin_client, policy_factory, insurance_type_factory
):
    today = timezone.localdate()
    source = policy_factory(
        insurance_type=insurance_type_factory(name="ОСАГО", is_osago=True),
        vin_number="VINLINK001",
        franchise=0,
    )
    kind = insurance_type_factory(name="КАСКО")
    expected = {}
    for name, start, end, active, termination, status in (
        ("CURRENT", -30, 30, True, None, "Действует"),
        ("PLANNED-TERMINATION", -30, 30, False, 5, "Действует"),
        ("UPCOMING", 1, 31, True, None, "Предстоящий"),
        ("EXPIRED", -60, -1, True, None, "Завершён"),
        ("TERMINATED", -30, 30, False, -1, "Расторгнут"),
    ):
        contract = policy_factory(
            policy_number=name,
            insurance_type=kind,
            vin_number=source.vin_number,
            start_date=today + timedelta(days=start),
            end_date=today + timedelta(days=end),
            policy_active=active,
            termination_date=today + timedelta(days=termination)
            if termination is not None
            else None,
        )
        expected[contract.pk] = status
    response = admin_client.get(reverse("policies:detail", args=[source.pk]))
    assert response.status_code == 200
    assert {
        contract.pk: status for contract, status in response.context["related_policies"]
    } == expected
