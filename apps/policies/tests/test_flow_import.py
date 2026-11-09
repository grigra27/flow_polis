from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.urls import reverse

from apps.policies.models import FlowPolicySource, Policy
from apps.policies.services import flow_client
from apps.policies.services.flow_import import (
    candidate_policies,
    prepare_initial,
    save_linked_policy,
)


@pytest.fixture
def snapshot():
    return {
        "schema_version": 1,
        "source": "zs",
        "summary_id": 314,
        "revision": "r1",
        "request_id": 12,
        "client_name": "Тест",
        "client_inn": "9876543210",
        "dfa_number": "007 – МСК",
        "branch": "Москва",
        "selected_company": "СК",
        "insurance_type": "КАСКО",
        "manager_name": "",
        "insured_party": "lessee",
        "property_description": "Объект",
        "property_year": 2025,
        "source_object_count": 1,
        "variant": 1,
        "available_variants": [1],
        "offers": [
            {
                "year": 1,
                "insurance_sum": "10000.00",
                "premium": "100.00",
                "franchise": "0",
                "installments": 3,
            },
            {
                "year": 2,
                "insurance_sum": "8000.00",
                "premium": "79.90",
                "franchise": "0",
                "installments": 1,
            },
        ],
    }


def test_rows_and_catalogs(
    snapshot,
    sample_client,
    insurer_factory,
    insurance_type_factory,
    branch_factory,
    commission_rate_factory,
):
    branch = branch_factory(branch_name="Москва")
    insurer = insurer_factory(insurer_name="СК")
    kind = insurance_type_factory(name="КАСКО")
    commission_rate_factory(
        insurer=insurer, insurance_type=kind, kv_percent=Decimal("10")
    )
    initial = prepare_initial(snapshot)
    assert initial["policy"]["branch"] == branch.pk
    assert (
        initial["policy"]["policyholder"]
        == initial["policy"]["client"]
        == sample_client.pk
    )
    assert [row["amount"] for row in initial["payments"]] == [
        Decimal(v) for v in ("33.33", "33.33", "33.34", "79.90")
    ]
    assert initial["payments"][3]["insurance_sum"] == "8000.00"
    assert initial["payments"][3]["kv_rub"] == Decimal("7.99")
    assert all("due_date" not in row for row in initial["payments"])
    snapshot["source_object_count"] = 3
    assert all(
        "amount" not in row and "insurance_sum" not in row
        for row in prepare_initial(snapshot, slot=1)["payments"]
    )


def test_link_existing_and_guard_retries(snapshot, policy_factory, admin_user):
    existing = policy_factory(dfa_number="007-МСК")
    assert list(candidate_policies(" 007 – мск ")) == [existing]
    assert not candidate_policies("ПРЕДВАРИТЕЛЬНАЯ")
    snapshot.update(variant=None, offers=[])
    result, added = save_linked_policy(
        snapshot, 0, admin_user, existing_policy=existing
    )
    assert result.pk == existing.pk and added
    callback = Mock(side_effect=AssertionError("duplicate policy created"))
    result, added = save_linked_policy(snapshot, 0, admin_user, create_policy=callback)
    assert result == existing and not added
    existing.refresh_from_db()
    assert existing.dfa_number == "007-МСК"


def test_transaction_discards_partial_policy_on_inline_failure(
    snapshot, policy_factory, admin_user
):
    def save_invalid():
        policy_factory()
        raise ValueError("bad schedule")

    with pytest.raises(ValueError, match="bad schedule"):
        save_linked_policy(snapshot, 0, admin_user, create_policy=save_invalid)
    assert Policy.objects.count() == FlowPolicySource.objects.count() == 0


def test_split_mode_prevents_cross_unit_reuse(snapshot, policy_factory, admin_user):
    existing = policy_factory(dfa_number=snapshot["dfa_number"])
    snapshot["source_object_count"] = 3
    save_linked_policy(snapshot, 1, admin_user, existing_policy=existing)
    for incorrect_slot in (0, 2, 4):
        with pytest.raises(flow_client.FlowError):
            save_linked_policy(
                snapshot, incorrect_slot, admin_user, existing_policy=existing
            )
    assert existing.flow_links.count() == 1


def test_link_rechecks_corrected_dfa_and_permission(
    snapshot, policy_factory, admin_user
):
    existing = policy_factory(dfa_number="123")
    snapshot["dfa_number"] = "ПРЕДВАРИТЕЛЬНАЯ"
    with pytest.raises(flow_client.FlowError):
        save_linked_policy(snapshot, 0, admin_user, existing_policy=existing)
    result, added = save_linked_policy(
        snapshot, 0, admin_user, existing_policy=existing, dfa_number="123"
    )
    assert result == existing and added
    admin_user.is_staff = False
    with pytest.raises(PermissionDenied):
        save_linked_policy(
            snapshot, 0, admin_user, existing_policy=existing, dfa_number="123"
        )


@override_settings(FLOW_HANDOFF_ENABLED=True, FLOW_SERVICE_TOKEN="flow-test-service")
def test_status_is_authenticated_and_does_not_disclose_policy_details(
    snapshot, policy_factory, admin_user, client
):
    url = reverse("flow-link-status", args=[snapshot["summary_id"]])
    assert client.get(url).status_code == 401
    headers = {"authorization": "Bearer flow-test-service"}
    assert client.get(url, headers=headers).json() == {
        "total": 0,
        "mode": None,
        "links": [],
    }
    p = policy_factory(dfa_number=snapshot["dfa_number"])
    save_linked_policy(snapshot, 0, admin_user, existing_policy=p)
    resp = client.get(url, headers=headers)
    assert resp.json() == {
        "total": 1,
        "mode": "common",
        "links": [{"position": 1, "policy_number": p.policy_number, "policy_id": p.pk}],
    }
    assert "no-store" in resp["Cache-Control"]
    with override_settings(FLOW_HANDOFF_ENABLED=False):
        assert client.get(url, headers=headers).json() == resp.json()


@override_settings(
    FLOW_HANDOFF_ENABLED=True,
    FLOW_SERVICE_TOKEN="flow-test-service",
    FLOW_ZS_BASE_URL="https://zs.example",
)
def test_client_rejects_redirect_inactive_and_wrong_id(snapshot):
    reply = Mock(status_code=302)
    with patch(
        "apps.policies.services.flow_client.requests.request", return_value=reply
    ) as request:
        with pytest.raises(flow_client.FlowError):
            flow_client.exchange_ticket("ticket")
        assert request.call_args.kwargs["allow_redirects"] is False
        reply.status_code = 409
        with pytest.raises(flow_client.FlowError):
            flow_client.fetch_snapshot(314)
        reply.status_code = 200
        reply.json.return_value = {"snapshot": snapshot}
        with pytest.raises(flow_client.FlowError):
            flow_client.fetch_snapshot(315)
        assert flow_client.fetch_snapshot(314)["revision"] == "r1"


def test_link_only_permission_and_protected_relationship(
    snapshot, policy_factory, django_user_model
):
    from django.contrib.auth.models import Permission
    from django.db.models.deletion import ProtectedError

    manager = django_user_model.objects.create_user("link_only", is_staff=True)
    manager.user_permissions.add(Permission.objects.get(codename="link_flow_policy"))
    policy = policy_factory(dfa_number=snapshot["dfa_number"])
    with pytest.raises(PermissionDenied):
        save_linked_policy(snapshot, 0, manager, create_policy=Mock())
    save_linked_policy(snapshot, 0, manager, existing_policy=policy)
    with pytest.raises(ProtectedError):
        policy.delete()


@pytest.mark.parametrize(
    "change",
    [
        {"year": 11},
        {"installments": 999999},
        {"insurance_sum": "0.00"},
        {"premium": "-1.00"},
        {"premium": "1e9999999999"},
        {"franchise": "nan"},
    ],
)
def test_rejects_invalid_financial_data(snapshot, change):
    snapshot["offers"][0].update(change)
    with pytest.raises(ValueError):
        flow_client._validate_snapshot(snapshot)


@pytest.mark.django_db(transaction=True)
def test_concurrent_creations_share_one_policy_and_link(
    snapshot, policy_factory, admin_user
):
    """Separate PostgreSQL sessions race on the first INSERT for this summary."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.contrib.auth import get_user_model
    from django.db import connection, connections

    if connection.vendor != "postgresql":
        pytest.skip("Проверка блокировки строк требует PostgreSQL")
    template = policy_factory()
    ready = Barrier(2)

    def run():
        try:
            user = get_user_model().objects.get(pk=admin_user.pk)
            ready.wait(timeout=10)

            def create():
                return policy_factory(
                    client=template.client,
                    insurer=template.insurer,
                    branch=template.branch,
                    insurance_type=template.insurance_type,
                    policy_number="FLOW-RACE",
                )

            p, added = save_linked_policy(snapshot, 0, user, create_policy=create)
            return p.pk, added
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(lambda _: run(), range(2))
    assert a[0] == b[0]
    assert sorted((a[1], b[1])) == [False, True]
    assert Policy.objects.filter(policy_number="FLOW-RACE").count() == 1
