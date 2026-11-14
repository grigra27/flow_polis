from datetime import date
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.policies.models import FlowPolicySource
from apps.policies.services import flow_groups
from apps.policies.services.flow_client import FlowError
from .test_flow_ui import admin_post_values, open_review, source


def plan(client, url, start, end, dfa, **kwargs):
    page = client.get(url)
    return client.post(
        url,
        dict(
            action="plan",
            range_start=start,
            range_end=end,
            group_dfa=dfa,
            plan_version=page.context["plan_version"],
            **kwargs,
        ),
    )


def split_data(client, url, number):
    data = admin_post_values(client, url)
    data.update(
        policy_number=number,
        vin_number="ABC000111",
        property_description="Проверенный объект",
    )
    for index in range(2):
        data[f"payment_schedule-{index}-amount"] = "12"
        data[f"payment_schedule-{index}-insurance_sum"] = "1000"
    return data


def test_group_template_from_validated_form_persists_per_range(admin_client, source):
    source["source_object_count"] = 4
    review = open_review(admin_client, source)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert plan(admin_client, review, 1, 2, "GROUP-A").status_code == 302
        assert plan(admin_client, review, 3, 4, "GROUP-B").status_code == 302
        assert plan(admin_client, review, 2, 3, "OVERLAP").status_code == 409
        group = FlowPolicySource.objects.get()
        assert len(group.groups) == 2 and not group.links.exists()
        assert not admin_client.get(review).context["allow_common"]
        first = admin_client.post(review, {"action": "new", "slot": 1}).url
        assert first.startswith(reverse("policies:flow-add"))
        data = split_data(admin_client, first, "FIRST")
        assert data["dfa_number"] == "GROUP-A"
        data["payment_schedule-0-paid_date"] = date.today().isoformat()
        data.update(_flow_template="yes", _flow_next="yes")
        second = admin_client.post(first, data).url
        next_form = admin_client.get(second)
        assert next_form.templates[0].name == "policies/flow_form.html"
        conditions = next_form.context["flow_group"]
        assert conditions["template_policy_number"] == "FIRST"
        assert next_form.context["flow_slot"] == 2
        initial = next_form.context["adminform"].form.initial
        assert not initial.get("vin_number") and not initial.get("policy_number")
        assert initial["property_description"] == source["property_description"]
        assert initial["start_date"] == date.fromisoformat(data["start_date"])
        second_data = admin_post_values(admin_client, second)
        assert second_data["payment_schedule-0-amount"] == "12.00"
        assert not second_data.get("payment_schedule-0-paid_date")
        second_data.update(policy_number="SECOND", _flow_next="yes")
        third = admin_client.post(second, second_data).url
        third_data = admin_post_values(admin_client, third)
        assert third_data["dfa_number"] == "GROUP-B"
        assert (
            not third_data.get("payment_schedule-0-amount")
            and "start_date" in third_data
        )
        # Новый переход из ЗС видит сохранённый план и текущую свободную позицию.
        fresh = open_review(admin_client, source)
        page = admin_client.get(fresh)
        assert (
            page.context["selected_slot"] == 3
            and page.context["search_dfa"] == "GROUP-B"
        )
        link = group.links.get(slot=1)
        preview = admin_client.get(fresh, {"sample": link.policy_id})
        assert "Взнос на один объект" in preview.content.decode()
        # Отдельная группа явно выбирает образец у уже сохранённого полиса.
        assert (
            plan(
                admin_client, fresh, 3, 4, "GROUP-B", template_policy_id=link.policy_id
            ).status_code
            == 409
        )
        assert (
            plan(
                admin_client,
                fresh,
                3,
                4,
                "GROUP-B",
                template_policy_id=link.policy_id,
                confirm_template="yes",
            ).status_code
            == 302
        )
        group.refresh_from_db()
        assert group.groups[1]["template"]["payments"][0]["amount"] == "12.00"
        for view in ("policies:detail", "admin:policies_policy_change"):
            page = admin_client.get(reverse(view, args=[link.policy_id]))
            assert (
                link.source_label in page.content.decode()
                and link.source_url in page.content.decode()
            )


def test_stale_group_plan_keeps_manual_values_and_can_reset_empty_source(
    admin_client, source
):
    source["source_object_count"] = 4
    review = open_review(admin_client, source)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert plan(admin_client, review, 1, 4, "OLD").status_code == 302
        first = admin_client.post(review, {"action": "new", "slot": 1}).url
        data = split_data(admin_client, first, "MANUAL")
        assert plan(admin_client, review, 1, 4, "NEW").status_code == 302
        response = admin_client.post(first, data, follow=True)
        assert response.context["search_dfa"] == "NEW"
        res = admin_client.post(
            response.request["PATH_INFO"], {"action": "new", "slot": 1}
        )
        restored = admin_client.get(res.url).context["adminform"].form.initial
        assert restored["policy_number"] == "MANUAL" and restored["dfa_number"] == "NEW"
        current_data = split_data(admin_client, res.url, "MANUAL")
        delete = {
            "action": "remove-group",
            "range_start": 1,
            "range_end": 4,
            "plan_version": admin_client.get(review).context["plan_version"],
        }
        assert admin_client.post(review, delete).status_code == 302
        unassigned = admin_client.post(res.url, current_data, follow=True)
        assert unassigned.context["search_dfa"] == source["dfa_number"]
        assert plan(admin_client, review, 1, 4, "OLD").status_code == 302
    smaller = dict(source, source_object_count=2, revision="new")
    fresh = open_review(admin_client, smaller)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=smaller
    ):
        assert plan(admin_client, fresh, 1, 2, "REPLACED").status_code == 302
    group = FlowPolicySource.objects.get()
    assert (
        group.total == 2
        and len(group.groups) == 1
        and group.groups[0]["dfa"] == "REPLACED"
    )


def test_foreign_client_cannot_become_a_template(source, policy_factory):
    policy = policy_factory()
    with pytest.raises(FlowError, match="лизингополучатель|ИНН"):
        flow_groups.set_template({}, policy, source)


def test_status_batch_shows_empty_plan_and_existing_link(
    client, source, policy_factory, settings, django_assert_num_queries
):
    settings.FLOW_SERVICE_TOKEN = "internal-test"
    group = FlowPolicySource.objects.create(summary_id=12, total=4, mode="separate")
    empty = FlowPolicySource.objects.create(summary_id=13, total=2, mode="separate")
    policy = policy_factory()
    group.links.create(slot=2, policy=policy, revision="r", created_from_summary=True)
    url = reverse("flow-batch-link-status")
    auth = {
        "HTTP_AUTHORIZATION": "Bearer internal-test",
        "content_type": "application/json",
    }
    assert (
        client.post(
            url, {"summary_ids": [12]}, content_type="application/json"
        ).status_code
        == 401
    )
    for malformed in ([True], [0], list(range(1, 102)), "12"):
        assert client.post(url, {"summary_ids": malformed}, **auth).status_code == 400
    with django_assert_num_queries(1):
        response = client.post(url, {"summary_ids": [12, 13, 14]}, **auth)
    payload = response.json()["summaries"]
    assert payload["12"] == {
        "mode": "separate",
        "total": 4,
        "links": [
            {
                "position": 2,
                "policy_id": policy.pk,
                "policy_number": policy.policy_number,
                "in_force": True,
            }
        ],
    }
    assert payload[str(empty.pk)] == {"mode": "separate", "total": 2, "links": []}
    assert payload["14"] == {"mode": None, "total": 0, "links": []}


def test_reviewed_dfa_format_keeps_existing_group_editable(
    admin_client, source, policy_factory
):
    source["source_object_count"] = 2
    policy = policy_factory(dfa_number="12345-1")
    linked_source = FlowPolicySource.objects.create(
        summary_id=source["summary_id"],
        total=2,
        mode="separate",
        groups=[
            dict(
                first_slot=1,
                last_slot=2,
                dfa="ТС-12345/1",
                revision=source["revision"],
                version="original-plan",
            )
        ],
    )
    url = reverse("policies:link-zs-confirm", args=[policy.pk, source["summary_id"]])
    with patch(
        "apps.policies.reverse_flow_views.flow_client.fetch_snapshot",
        return_value=source,
    ):
        page = admin_client.get(url)
        assert page.status_code == 200
        response = admin_client.post(
            url,
            {
                "confirmation_token": page.context["confirmation_token"],
                "slot": "1",
                "confirm": "yes",
                "acknowledge": "yes",
            },
        )
    assert response.status_code == 302
    assert linked_source.links.get().policy_id == policy.pk

    data = dict(
        range_start="1",
        range_end="2",
        group_dfa="ТС-12345/1",
        plan_version=flow_groups.plan_version(linked_source.groups),
    )
    flow_groups.edit_plan(source, data)
    linked_source.refresh_from_db()
    assert linked_source.groups[0]["dfa"] == "ТС-12345/1"
    assert linked_source.groups[0]["version"] != "original-plan"
    current_groups = linked_source.groups
    data.update(
        group_dfa="ТС-12345/2", plan_version=flow_groups.plan_version(current_groups)
    )
    with pytest.raises(FlowError, match="другой окончательный ДФА"):
        flow_groups.edit_plan(source, data)
    linked_source.refresh_from_db()
    assert linked_source.groups == current_groups
    policy.refresh_from_db()
    assert policy.dfa_number == "12345-1"
