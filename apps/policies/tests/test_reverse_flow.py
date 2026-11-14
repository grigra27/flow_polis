from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.policies.models import (
    FlowPolicyLink,
    FlowPolicySource,
    Policy,
    PaymentSchedule,
)
from apps.policies.services import flow_client, flow_import
from apps.policies.services.flow_matching import dfa_match

pytestmark = pytest.mark.django_db


@pytest.fixture
def target(settings, policy_factory):
    settings.FLOW_HANDOFF_ENABLED = True
    settings.FLOW_ZS_BASE_URL = "https://zs.example"
    settings.FLOW_SERVICE_TOKEN = "test-service-token"
    return policy_factory(
        dfa_number="12345-1",
        end_date=timezone.localdate() - timedelta(days=1),
        start_date=timezone.localdate() - timedelta(days=366),
    )


@pytest.fixture
def snapshot(target):
    return dict(
        schema_version=1,
        source="zs",
        summary_id=41,
        request_id=31,
        revision="r1",
        dfa_number="ТС-12345/1",
        client_name=target.client.client_name,
        client_inn=target.client.client_inn,
        selected_company=target.insurer.insurer_name,
        insurance_type=target.insurance_type.name,
        property_description=target.property_description,
        source_object_count=1,
        variant=None,
        offers=[],
        available_variants=[],
        accepted_at=timezone.now().isoformat(),
        item_no=1,
        item_count=1,
        branch=target.branch.branch_name,
        insured_party="lessee",
        manager_name="",
    )


def confirm_url(target, snapshot):
    return reverse("policies:link-zs-confirm", args=[target.pk, snapshot["summary_id"]])


def read_confirm(client, target, snapshot):
    with patch(
        "apps.policies.reverse_flow_views.flow_client.fetch_snapshot",
        return_value=snapshot,
    ):
        response = client.get(confirm_url(target, snapshot))
    assert response.status_code == 200
    return response


def post_confirm(client, target, snapshot, data):
    with patch(
        "apps.policies.reverse_flow_views.flow_client.fetch_snapshot",
        return_value=snapshot,
    ):
        return client.post(confirm_url(target, snapshot), data)


def confirmation(response, slot=0):
    return dict(
        confirmation_token=response.context["confirmation_token"],
        slot=str(slot),
        confirm="yes",
        acknowledge="yes",
    )


@pytest.mark.parametrize(
    "left,right,kind",
    [
        ("ТС-12345/1", "12345-1", "structure"),
        ("TS/12345/1", "12345-1", "structure"),
        ("12345-1", "12345-1", "exact"),
        ("12345", "12345-1", "base"),
        ("12345-1", "12345-2", ""),
        ("12345-1", "123451", ""),
        ("00123", "123", ""),
        ("001-Ф", "001-ф", "exact"),
    ],
)
def test_matching_keeps_structure(left, right, kind):
    assert dfa_match(left, right) == kind


def test_link_existing_preserves_all_policy_and_payment_fields(
    admin_client, admin_user, target, snapshot, payment_schedule_factory
):
    payment_schedule_factory(policy=target, paid_date=timezone.localdate())
    before = Policy.objects.values().get(pk=target.pk)
    payments = list(PaymentSchedule.objects.filter(policy=target).values())
    response = read_confirm(admin_client, target, snapshot)
    assert not FlowPolicySource.objects.exists()
    data = confirmation(response)
    response = post_confirm(admin_client, target, snapshot, data)
    assert response.status_code == 302
    link = FlowPolicyLink.objects.get()
    assert (
        link.policy_id,
        link.source_id,
        link.slot,
        link.created_by_id,
        link.created_from_summary,
    ) == (target.pk, 41, 0, admin_user.pk, False)
    assert Policy.objects.values().get(pk=target.pk) == before
    assert list(PaymentSchedule.objects.filter(policy=target).values()) == payments
    assert post_confirm(admin_client, target, snapshot, data).status_code == 302
    assert FlowPolicyLink.objects.count() == 1


def test_warning_acknowledgement_required(admin_client, target, snapshot):
    data = confirmation(read_confirm(admin_client, target, snapshot))
    data.pop("acknowledge")
    assert post_confirm(admin_client, target, snapshot, data).status_code == 409
    assert not FlowPolicySource.objects.exists()


@pytest.mark.parametrize(
    "field,value", [("confirmation_token", "tampered"), ("slot", "1"), ("confirm", "")]
)
def test_tampering_and_unconfirmed_request_rejected(
    admin_client, target, snapshot, field, value
):
    data = confirmation(read_confirm(admin_client, target, snapshot))
    data[field] = value
    assert post_confirm(admin_client, target, snapshot, data).status_code == 409
    assert not FlowPolicyLink.objects.exists()


def test_token_bound_to_policy_and_user(
    admin_client, client, django_user_model, target, snapshot, policy_factory
):
    data = confirmation(read_confirm(admin_client, target, snapshot))
    other = policy_factory(
        policy_number="other",
        dfa_number=target.dfa_number,
        insurance_type=target.insurance_type,
    )
    assert post_confirm(admin_client, other, snapshot, data).status_code == 409
    user = django_user_model.objects.create_user("linker", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="link_flow_policy"))
    client.force_login(user)
    assert post_confirm(client, target, snapshot, data).status_code == 409
    fresh = read_confirm(client, target, snapshot)
    assert (
        post_confirm(client, target, snapshot, confirmation(fresh)).status_code == 302
    )


@pytest.mark.parametrize("method", ["get", "post"])
def test_reader_cannot_search_or_confirm(
    client, django_user_model, target, snapshot, method
):
    client.force_login(django_user_model.objects.create_user("reader"))
    with patch("apps.policies.reverse_flow_views.flow_client.fetch_snapshot") as remote:
        response = getattr(client, method)(confirm_url(target, snapshot))
        assert response.status_code == 403
        remote.assert_not_called()
    assert (
        client.get(reverse("policies:link-zs-search", args=[target.pk])).status_code
        == 403
    )


def test_anonymous_and_disabled_feature(
    client, admin_client, settings, target, snapshot
):
    assert client.get(confirm_url(target, snapshot)).status_code == 302
    settings.FLOW_HANDOFF_ENABLED = False
    assert admin_client.get(confirm_url(target, snapshot)).status_code == 404


@pytest.mark.parametrize("change", ["policy", "client", "revision", "plan"])
def test_stale_confirmation_requires_review(admin_client, target, snapshot, change):
    data = confirmation(read_confirm(admin_client, target, snapshot))
    if change == "policy":
        Policy.objects.filter(pk=target.pk).update(dfa_number="98765")
    elif change == "client":
        target.client.client_inn = "9988776655"
        target.client.save()
    elif change == "revision":
        snapshot = dict(snapshot, revision="r2")
    else:
        FlowPolicySource.objects.create(summary_id=41, mode="separate", total=2)
    response = post_confirm(admin_client, target, snapshot, data)
    assert response.status_code == 409
    assert not FlowPolicyLink.objects.exists()


def test_occupied_slot_is_conflict_not_success(
    admin_client, target, snapshot, policy_factory
):
    data = confirmation(read_confirm(admin_client, target, snapshot))
    other = policy_factory(
        policy_number="other",
        dfa_number=target.dfa_number,
        insurance_type=target.insurance_type,
    )
    source = FlowPolicySource.objects.create(summary_id=41, mode="common", total=1)
    source.links.create(policy=other, slot=0, revision="r1", created_from_summary=False)
    response = post_confirm(admin_client, target, snapshot, data)
    assert response.status_code == 409
    assert "другим полисом" in response.context["error"]
    assert not target.flow_links.exists()


def test_group18_free_slot_and_final_dfa(
    admin_client, target, snapshot, policy_factory
):
    snapshot = dict(snapshot, source_object_count=18, dfa_number="ТС-77777/1")
    target.dfa_number = "88888-1"
    target.save()
    source = FlowPolicySource.objects.create(
        summary_id=41,
        mode="separate",
        total=18,
        groups=[
            dict(
                first_slot=16, last_slot=18, dfa="88888-1", revision="r1", version="g1"
            )
        ],
    )
    for slot in range(1, 16):
        source.links.create(
            policy=policy_factory(
                policy_number=f"P{slot}", insurance_type=target.insurance_type
            ),
            slot=slot,
            revision="r1",
            created_from_summary=False,
        )
    response = read_confirm(admin_client, target, snapshot)
    slots = response.context["slots"]
    assert len(slots) == 18 and sum(not r["disabled"] for r in slots) == 3
    assert [row["value"] for row in response.context["available_slots"]] == [16, 17, 18]
    assert len(response.context["unavailable_slots"]) == 15
    assert (
        post_confirm(
            admin_client, target, snapshot, confirmation(response, 16)
        ).status_code
        == 302
    )
    assert target.flow_links.get().slot == 16
    assert source.links.count() == 16


def test_group_dfa_different_suffix_cannot_be_overridden(
    admin_client, target, snapshot
):
    snapshot = dict(snapshot, source_object_count=2)
    FlowPolicySource.objects.create(
        summary_id=41,
        mode="separate",
        total=2,
        groups=[
            dict(first_slot=1, last_slot=2, dfa="12345-2", revision="r1", version="g1")
        ],
    )
    response = read_confirm(admin_client, target, snapshot)
    assert not response.context["can_confirm"]
    assert (
        post_confirm(
            admin_client, target, snapshot, confirmation(response, 1)
        ).status_code
        == 409
    )


def test_group_equivalent_format_is_reviewed_not_global(admin_client, target, snapshot):
    snapshot = dict(snapshot, source_object_count=2)
    FlowPolicySource.objects.create(
        summary_id=41,
        mode="separate",
        total=2,
        groups=[
            dict(
                first_slot=1, last_slot=2, dfa="ТС-12345/1", revision="r1", version="g1"
            )
        ],
    )
    response = read_confirm(admin_client, target, snapshot)
    assert (
        post_confirm(
            admin_client, target, snapshot, confirmation(response, 1)
        ).status_code
        == 302
    )


def test_empty_plan_can_select_common(admin_client, target, snapshot):
    snapshot = dict(snapshot, source_object_count=18)
    FlowPolicySource.objects.create(summary_id=41, mode="separate", total=18)
    response = read_confirm(admin_client, target, snapshot)
    assert (
        post_confirm(
            admin_client, target, snapshot, confirmation(response, 0)
        ).status_code
        == 302
    )
    assert FlowPolicySource.objects.get().mode == "common"


def test_manual_dfa_mismatch_is_explicit_and_does_not_change_numbers(
    admin_client, target, snapshot
):
    snapshot = dict(snapshot, dfa_number="ТС-54321")
    target.dfa_number = "99999"
    target.save()
    response = read_confirm(admin_client, target, snapshot)
    assert response.context["warnings"]
    assert (
        post_confirm(admin_client, target, snapshot, confirmation(response)).status_code
        == 302
    )
    target.refresh_from_db()
    assert target.dfa_number == "99999"


def test_unavailable_or_revoked_source_is_not_empty_results(
    admin_client, target, snapshot
):
    with patch(
        "apps.policies.reverse_flow_views.flow_client.fetch_snapshot",
        side_effect=flow_client.FlowError("Акцепт недоступен"),
    ):
        response = admin_client.get(confirm_url(target, snapshot))
    assert response.status_code == 409 and not response.context["can_confirm"]
    assert not FlowPolicyLink.objects.exists()


def search_row(snapshot):
    return dict(
        snapshot, match_kind="structure", match_label="Совпала цифровая структура ДФА"
    )


def test_search_single_call_includes_local_final_dfa_plan(
    admin_client, target, snapshot
):
    snapshot = dict(snapshot, dfa_number="ТС-77777/1", source_object_count=18)
    FlowPolicySource.objects.create(
        summary_id=41,
        mode="separate",
        total=18,
        groups=[
            dict(
                first_slot=1,
                last_slot=18,
                dfa=target.dfa_number,
                revision="r1",
                version="g1",
            )
        ],
    )
    with patch(
        "apps.policies.reverse_flow_views.flow_client.search_summaries",
        return_value={"results": [search_row(snapshot)], "page": 1, "has_next": False},
    ) as search, patch(
        "apps.policies.reverse_flow_views.flow_client.fetch_snapshot"
    ) as detail:
        response = admin_client.get(
            reverse("policies:link-zs-search", args=[target.pk])
        )
    assert response.status_code == 200
    assert search.call_args.kwargs["summary_ids"] == [41]
    assert response.context["candidates"][0]["group_match"]
    detail.assert_not_called()
    assert not FlowPolicyLink.objects.exists()


def test_search_http_contract_and_malformed_response(target, snapshot):
    data = {"results": [search_row(snapshot)], "page": 1, "has_next": True}
    with patch(
        "apps.policies.services.flow_client.requests.request",
        return_value=Mock(status_code=200, json=Mock(return_value=data)),
    ) as request:
        assert (
            flow_client.search_summaries(dfa=target.dfa_number, summary_ids=[41])
            == data
        )
        assert request.call_args.kwargs["params"]["summary_ids"] == "41"
        assert request.call_args.kwargs["allow_redirects"] is False
        data["results"][0]["summary_id"] = True
        with pytest.raises(flow_client.FlowError):
            flow_client.search_summaries(dfa=target.dfa_number)


def test_search_failure_explains_unavailable(admin_client, target):
    with patch(
        "apps.policies.reverse_flow_views.flow_client.search_summaries",
        side_effect=flow_client.FlowError("Сервер ЗС недоступен"),
    ):
        response = admin_client.get(
            reverse("policies:link-zs-search", args=[target.pk])
        )
    assert response.status_code == 503
    assert "недоступен" in response.context["error"]


def test_old_strict_linking_does_not_accept_new_format_by_default(
    admin_user, target, snapshot
):
    with pytest.raises(flow_client.FlowError):
        flow_import.save_linked_policy(snapshot, 0, admin_user, existing_policy=target)
    assert not FlowPolicySource.objects.exists()


def test_accepted_label_uses_moscow_date():
    from apps.policies.reverse_flow_views import _accepted_label

    with timezone.override("Europe/Moscow"):
        assert _accepted_label("2026-11-13T22:30:00Z") == "14.11.2026"
        assert _accepted_label("2026-11-13T20:30:00+00:00") == "13.11.2026"
        assert _accepted_label(None) == "—"
