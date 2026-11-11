import secrets
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.policies.models import FlowPolicyLink, FlowPolicySource, Policy


@pytest.fixture
def source(
    settings, sample_client, branch_factory, insurer_factory, insurance_type_factory
):
    settings.FLOW_HANDOFF_ENABLED = True
    settings.FLOW_ZS_BASE_URL = "https://zs.example"
    branch = branch_factory(branch_name="Москва")
    insurer = insurer_factory(insurer_name="Страховая")
    kind = insurance_type_factory(name="КАСКО")
    return {
        "schema_version": 1,
        "source": "zs",
        "revision": "original",
        "summary_id": 7,
        "request_id": 5,
        "dfa_number": "001-Ф",
        "client_name": sample_client.client_name,
        "client_inn": sample_client.client_inn,
        "insured_party": "lessee",
        "branch": branch.branch_name,
        "selected_company": insurer.insurer_name,
        "insurance_type": kind.name,
        "manager_name": "",
        "property_year": None,
        "property_description": "Кран",
        "source_object_count": 1,
        "variant": 1,
        "offers": [
            {
                "year": 1,
                "insurance_sum": "5000.00",
                "premium": "100.00",
                "franchise": "0",
                "installments": 2,
            }
        ],
    }


def open_review(client, source):
    with patch(
        "apps.policies.flow_views.flow_client.exchange_ticket", return_value=source
    ):
        resp = client.get(
            reverse("flow_policy_landing"), {"code": "test-ticket"}, follow=True
        )
    assert resp.status_code == 200
    return resp.redirect_chain[-1][0]


def new_form(client, url, source):
    if "flow_draft=" in url:
        return url
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        res = client.post(url, {"action": "new", "slot": "0", "candidates": ""})
    assert res.status_code == 302
    return res.url


def admin_post_values(client, url):
    response = client.get(url)
    assert response.status_code == 200
    form = response.context["adminform"].form
    today = date.today()
    data = {
        k: str(v) for k, v in form.initial.items() if k in form.fields and v is not None
    }
    data.update(
        policy_number="REAL-7",
        start_date=today.isoformat(),
        end_date=(today + timedelta(days=360)).isoformat(),
        policy_active="on",
        dfa_active="on",
        broker_participation="on",
    )
    for inline in response.context["inline_admin_formsets"]:
        fs = inline.formset
        data.update(
            {
                fs.management_form.add_prefix(name): v
                for name, v in fs.management_form.initial.items()
            }
        )
        if fs.prefix != "payment_schedule":
            continue
        assert fs.total_form_count() == 2
        for index, row in enumerate(fs.forms):
            for k, v in row.initial.items():
                if k in row.fields and v is not None:
                    data[row.add_prefix(k)] = str(v)
            data[row.add_prefix("due_date")] = (
                today + timedelta(days=30 * index)
            ).isoformat()
            data[row.add_prefix("kv_rub")] = "0"
    return data


def test_new_policy_multirow_and_repeat(admin_client, source):
    review = open_review(admin_client, source)
    url = new_form(admin_client, review, source)
    data = admin_post_values(admin_client, url)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        res = admin_client.post(url, data)
        assert res.status_code == 302, (
            res.context["adminform"].form.errors if res.context else res.content
        )
        assert admin_client.post(url, data).url == res.url
    policy = FlowPolicyLink.objects.get().policy
    assert res.url == reverse("policies:detail", args=[policy.pk])
    assert (
        list(policy.payment_schedule.values_list("amount", flat=True))
        == [Decimal("50.00")] * 2
    )
    assert admin_client.get(url).url == res.url


def test_link_existing_and_preserve_record(admin_client, source, policy_factory):
    existing = policy_factory(
        dfa_number=source["dfa_number"], property_description="Исходное описание"
    )
    source["variant"], source["offers"] = None, []
    review = open_review(admin_client, source)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        res = admin_client.post(
            review,
            {
                "slot": 0,
                "action": "link",
                "policy_id": existing.pk,
                "candidates": str(existing.pk),
            },
        )
    assert res.url == reverse("policies:detail", args=[existing.pk])
    existing.refresh_from_db()
    assert existing.property_description == "Исходное описание"
    assert Policy.objects.count() == FlowPolicyLink.objects.count() == 1


def test_changed_source_and_duplicate_recheck(admin_client, source, policy_factory):
    review = open_review(admin_client, source)
    url = new_form(admin_client, review, source)
    data = admin_post_values(admin_client, url)
    p = policy_factory(dfa_number="99-Ф")
    data["dfa_number"] = p.dfa_number
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        response = admin_client.post(url, data)
        assert response.status_code == 200 and response.context["mark"] == str(p.pk)
        assert ("policy_number", "REAL-7") in response.context["hidden"]
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot",
        return_value=dict(source, revision="r2"),
    ):
        response = admin_client.post(url, {**data, "_flow_confirm": str(p.pk)})
    assert response.status_code == 302 and "/review/" in response.url
    assert not FlowPolicyLink.objects.exists()


def test_actual_premium_confirmation(admin_client, source):
    url = new_form(admin_client, open_review(admin_client, source), source)
    data = admin_post_values(admin_client, url)
    data["payment_schedule-0-amount"] = "60"
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        res = admin_client.post(url, data)
        assert res.status_code == 200 and "_flow_actual" in res.content.decode()
        assert not Policy.objects.exists()
        res = admin_client.post(url, {**data, "_flow_actual": "yes"})
        assert res.status_code == 302
    assert FlowPolicyLink.objects.get().policy.premium_total == Decimal("110")


def test_login_continues_handoff_without_ticket_in_next(client, admin_user, source):
    landing = reverse("flow_policy_landing")
    response = client.get(landing, {"code": "opaque-secret"})
    continuation = response.url
    assert continuation.startswith(landing + "?continue=")
    assert response["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response["Cache-Control"]
    assert (
        "opaque-secret" not in continuation
        and "opaque-secret" not in client.get(continuation).url
    )
    login_password = secrets.token_urlsafe(24)
    admin_user.set_password(login_password)
    admin_user.save()
    got = client.post(
        reverse("accounts:login"),
        {
            "username": admin_user.username,
            "password": login_password,
            "next": continuation,
        },
    )
    assert got.url == continuation
    with patch(
        "apps.policies.flow_views.flow_client.exchange_ticket", return_value=source
    ) as exchange:
        res = client.get(continuation)
        assert "flow_draft=" in res.url
        exchange.assert_called_once_with("opaque-secret")


def test_link_only_user_and_candidate_choices(
    client, django_user_model, source, policy_factory
):
    user = _local_user(django_user_model, "flow-link", ["link_flow_policy"])
    client.force_login(user)
    obj1 = policy_factory(dfa_number=source["dfa_number"], policy_number="POL-A")
    obj2 = policy_factory(
        dfa_number=source["dfa_number"],
        policy_number="POL-B",
        insurance_type=obj1.insurance_type,
    )
    url = open_review(client, source)
    content = client.get(url).content.decode()
    assert (
        "POL-A" in content
        and "POL-B" in content
        and "Создать отдельный полис" not in content
    )
    values = {"slot": 0, "candidates": f"{obj1.pk},{obj2.pk}"}
    assert client.post(url, {**values, "action": "new"}).status_code == 403
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert (
            client.post(
                url, {**values, "action": "link", "policy_id": obj2.pk}
            ).status_code
            == 302
        )
    assert FlowPolicyLink.objects.get().policy == obj2


def test_split_mode_requires_manager_amounts_and_resumes(admin_client, source):
    source["source_object_count"] = 2
    url = open_review(admin_client, source)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert admin_client.post(url, {"action": "new"}).status_code == 409
        res = admin_client.post(url, {"action": "new", "slot": 1})
        assert res.status_code == 302
        form_url = res.url
        rows = next(
            inline.formset.forms
            for inline in admin_client.get(form_url).context["inline_admin_formsets"]
            if inline.formset.prefix == "payment_schedule"
        )
        assert all(
            not row.initial.get("amount") and not row.initial.get("insurance_sum")
            for row in rows
        )
        data = admin_post_values(admin_client, form_url)
        for idx in range(2):
            data[f"payment_schedule-{idx}-amount"] = "12"
            data[f"payment_schedule-{idx}-insurance_sum"] = "100"
        assert admin_client.post(form_url, data).status_code == 302
        assert FlowPolicyLink.objects.get().slot == 1
        after = admin_client.get(url)
        assert after.status_code == 200 and after.context["slots"] == [2]
        assert (
            admin_client.post(
                url,
                {
                    "action": "new",
                    "slot": 0,
                    "candidates": str(FlowPolicyLink.objects.get().policy_id),
                },
            ).status_code
            == 409
        )


def test_save_and_next_for_eighteen_objects(admin_client, source, policy_factory):
    source["source_object_count"] = 18
    group = FlowPolicySource.objects.create(
        summary_id=source["summary_id"], mode="separate", total=18
    )
    reference = policy_factory(dfa_number="FINAL-3", policy_number="EXTERNAL")

    def fill_slot(slot):
        policy = policy_factory(
            policy_number=f"GROUP-{slot}",
            dfa_number=source["dfa_number"],
            client=reference.client,
            insurer=reference.insurer,
            branch=reference.branch,
            insurance_type=reference.insurance_type,
        )
        group.links.create(
            slot=slot,
            policy=policy,
            revision=source["revision"],
            created_from_summary=True,
        )

    for slot in range(1, 15):
        fill_slot(slot)
    review = open_review(admin_client, source)
    assert not admin_client.get(review).context["candidates"]
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        form15 = admin_client.post(review, {"action": "new", "slot": 15}).url
        data = admin_post_values(admin_client, form15)
        data.update(_flow_next="yes", policy_number="GROUP-15", vin_number="TESTVIN15")
        for index in range(2):
            data[f"payment_schedule-{index}-amount"] = "12"
            data[f"payment_schedule-{index}-insurance_sum"] = "100"

        open_drafts = set(admin_client.session["flow_policy_drafts"])
        invalid = admin_client.post(form15, dict(data, policy_number=""))
        assert (
            invalid.status_code == 200
            and "policy_number" in invalid.context["adminform"].form.errors
        )
        assert set(admin_client.session["flow_policy_drafts"]) == open_drafts
        assert group.links.count() == 14

        data["dfa_number"] = reference.dfa_number
        confirm = admin_client.post(form15, data)
        assert confirm.context["mark"] == str(reference.pk)
        assert ("_flow_next", "yes") in confirm.context["hidden"]
        confirmed = dict(
            confirm.context["hidden"], _flow_confirm=confirm.context["mark"]
        )
        form16 = admin_client.post(form15, confirmed).url
        assert admin_client.post(form15, confirmed).url == form16
        assert group.links.count() == 15
        assert group.links.get(slot=15).policy.dfa_number == "FINAL-3"

        next_page = admin_client.get(form16)
        assert next_page.context["flow_slot"] == 16
        assert next_page.context["flow_has_next"]
        initial = next_page.context["adminform"].form.initial
        assert initial["dfa_number"] == source["dfa_number"]
        assert not initial.get("policy_number") and not initial.get("vin_number")
        form16_data = admin_post_values(admin_client, form16)
        assert not form16_data.get("payment_schedule-0-amount")
        assert not form16_data.get("payment_schedule-0-insurance_sum")

        # Другой менеджер оформил № 17, пока первый заполнял № 16.
        fill_slot(17)
        data.update(policy_number="GROUP-16", dfa_number=source["dfa_number"])
        form18 = admin_client.post(form16, data).url
        last = admin_client.get(form18)
        assert last.context["flow_slot"] == 18
        assert b'name="_flow_next"' not in last.content
        assert "Сохранить полис и связать со сводом" in last.content.decode()
        # Старая страница могла ещё показывать «следующий» перед сохранением соседа.
        data["policy_number"] = "GROUP-18"
        finished = admin_client.post(form18, data)
        assert finished.url == reverse(
            "policies:detail", args=[group.links.get(slot=18).policy_id]
        )
        assert admin_client.post(form18, data).url == finished.url
    assert group.links.count() == 18
    assert Policy.objects.count() == 19  # 18 позиций и ранее существующий кандидат.


def test_save_and_next_can_confirm_an_existing_policy(
    admin_client, source, policy_factory
):
    source["source_object_count"] = 2
    review = open_review(admin_client, source)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        first = admin_client.post(review, {"action": "new", "slot": 1}).url
        existing = policy_factory(dfa_number="FINAL-2")
        data = admin_post_values(admin_client, first)
        data.update(dfa_number=existing.dfa_number, _flow_next="yes")
        confirm = admin_client.post(first, data)
        assert confirm.context["mark"] == str(existing.pk)
        values = dict(
            confirm.context["hidden"],
            _flow_link=existing.pk,
            _flow_confirm=confirm.context["mark"],
        )
        second = admin_client.post(first, values).url
    assert admin_client.get(second).context["flow_slot"] == 2
    link = FlowPolicyLink.objects.get()
    assert link.slot == 1 and link.policy == existing and not link.created_from_summary
    assert Policy.objects.count() == 1


def test_stale_terms_keep_manual_number_vin_and_dates(admin_client, source):
    url = open_review(admin_client, source)
    data = admin_post_values(admin_client, url)
    data["vin_number"] = "ABC12345"
    data["policy_number"] = "SOURCE-R2"
    data["franchise"] = "0.00"
    new = dict(
        source,
        revision="r2",
        offers=[dict(source["offers"][0], premium="200", franchise="1000")],
    )
    with patch("apps.policies.flow_views.flow_client.fetch_snapshot", return_value=new):
        result = admin_client.post(url, data, follow=True)
        assert "До изменения" in result.content.decode()
        fresh_url = admin_client.post(
            result.request["PATH_INFO"], {"action": "new", "slot": 0}
        ).url
        restored = admin_client.get(fresh_url)
    assert restored.context["adminform"].form.initial["policy_number"] == "SOURCE-R2"
    rows = next(
        inline.formset.forms
        for inline in restored.context["inline_admin_formsets"]
        if inline.formset.prefix == "payment_schedule"
    )
    assert rows[0].initial["amount"] == Decimal("100")
    assert rows[0].initial["due_date"] == data["payment_schedule-0-due_date"]
    assert restored.context["adminform"].form.initial["franchise"] == Decimal("1000")
    confirmed = admin_post_values(admin_client, fresh_url)
    with patch("apps.policies.flow_views.flow_client.fetch_snapshot", return_value=new):
        assert admin_client.post(fresh_url, confirmed).status_code == 302
    assert FlowPolicyLink.objects.get().policy.premium_total == Decimal("200")


def test_stale_rebuild_added_removed_rows_and_tags():
    from apps.policies.flow_views import typed_edits, apply_edits

    source = {
        "policy": {"franchise": Decimal("0.00")},
        "payments": [
            {"year_number": 1, "installment_number": i, "amount": Decimal("50")}
            for i in (1, 2)
        ],
    }
    filled = {
        "franchise": "0.00",
        "payment_schedule-TOTAL_FORMS": "3",
        "info_tags-TOTAL_FORMS": "1",
        "info_tags-0-info_field": "2",
        "info_tags-0-tag": "7",
    }
    for idx in range(3):
        prefix = f"payment_schedule-{idx}-"
        filled.update(
            {
                prefix + "year_number": "1",
                prefix + "installment_number": str(idx + 1),
                prefix + "amount": "50.00",
            }
        )
    filled.update(
        {"payment_schedule-1-DELETE": "on", "payment_schedule-2-alliance_paid": "on"}
    )
    edits = typed_edits(filled, source, 0)
    fresh = {
        "policy": {"franchise": Decimal("1000")},
        "payments": [
            {"year_number": 1, "installment_number": i, "amount": Decimal("80")}
            for i in (1, 2)
        ],
    }
    apply_edits(fresh, edits)
    assert fresh["policy"]["franchise"] == Decimal("1000")
    assert fresh["payments"][0]["amount"] == Decimal("80")
    assert [
        (int(r["installment_number"]), r.get("alliance_paid"))
        for r in fresh["payments"]
    ] == [(1, None), (3, True)]
    assert fresh["tags"] == [{"info_field": "2", "tag": "7"}]


def test_disappeared_candidate_never_creates_policy(
    admin_client, source, policy_factory
):
    url = open_review(admin_client, source)
    data = admin_post_values(admin_client, url)
    target = policy_factory(dfa_number="NEW-91")
    data["dfa_number"] = target.dfa_number
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        review = admin_client.post(url, data)
        assert review.context["mark"] == str(target.pk)
        target.dfa_number = "CHANGED"
        target.save()
        response = admin_client.post(
            url, dict(data, _flow_link=str(target.pk), _flow_confirm=str(target.pk))
        )
    assert response.status_code == 409
    assert Policy.objects.count() == 1 and not FlowPolicyLink.objects.exists()


def test_new_dfa_then_actual_premium_confirmation(admin_client, source, policy_factory):
    url = open_review(admin_client, source)
    data = admin_post_values(admin_client, url)
    target = policy_factory(dfa_number="AFTER-91")
    data.update(dfa_number=target.dfa_number)
    data["payment_schedule-0-amount"] = "60"
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert admin_client.post(url, data).context["mark"] == str(target.pk)
        amounts = admin_client.post(url, dict(data, _flow_confirm=str(target.pk)))
        assert "_flow_actual" in amounts.content.decode()
        saved = admin_client.post(url, dict(data, _flow_actual="yes"))
        assert saved.status_code == 302
    assert FlowPolicyLink.objects.get().policy.premium_total == Decimal("110.00")


@pytest.mark.parametrize(("second_kv", "expected"), [("0", "0"), ("", "5.00")])
def test_manual_commission_on_new_policy(
    admin_client, source, commission_rate_factory, second_kv, expected
):
    from apps.insurers.models import Insurer, InsuranceType

    commission_rate_factory(
        insurer=Insurer.objects.get(insurer_name=source["selected_company"]),
        insurance_type=InsuranceType.objects.get(name="КАСКО"),
        kv_percent=10,
    )
    url = open_review(admin_client, source)
    data = admin_post_values(admin_client, url)
    data["payment_schedule-0-kv_rub"] = "2.22"
    data["payment_schedule-1-kv_rub"] = second_kv
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert admin_client.post(url, data).status_code == 302
    assert list(
        FlowPolicyLink.objects.get().policy.payment_schedule.values_list(
            "kv_rub", flat=True
        )
    ) == [Decimal("2.22"), Decimal(expected)]


def _local_user(django_user_model, name, perms, staff=True):
    from django.contrib.auth.models import Permission

    user = django_user_model.objects.create_user(username=name, is_staff=staff)
    user.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label="policies", codename__in=perms
        )
    )
    return user


@pytest.mark.parametrize(
    "staff,grants",
    [
        (False, []),
        (
            False,
            ["add_policy", "add_paymentschedule", "change_policy", "link_flow_policy"],
        ),
        (True, ["view_policy", "change_policy"]),
        (True, ["add_policy"]),
    ],
)
def test_reader_sees_local_reason_before_exchange_and_forged_write_is_denied(
    client, django_user_model, source, policy_factory, staff, grants
):
    from apps.policies.flow_views import DRAFTS, PENDING
    from apps.policies.models import FlowPolicySource

    existing = policy_factory(dfa_number=source["dfa_number"])
    reader = _local_user(django_user_model, "local-polis-reader", grants, staff=staff)
    client.force_login(reader)
    assert client.get(reverse("policies:detail", args=[existing.pk])).status_code == 200
    with patch("apps.policies.flow_views.flow_client.exchange_ticket") as exchange:
        response = client.get(
            reverse("flow_policy_landing"), {"code": "zs-manager-ticket"}
        )
    assert (
        response.status_code == 403
        and "нет права создавать полисы" in response.content.decode()
    )
    assert (
        "no-store" in response["Cache-Control"]
        and response["Referrer-Policy"] == "no-referrer"
    )
    exchange.assert_not_called()
    assert not client.session.get(PENDING) and not client.session.get(DRAFTS)

    session = client.session
    session[DRAFTS] = {
        "forged": {
            "user_id": reader.pk,
            "snapshot": source,
            "dfa": source["dfa_number"],
            "slot": 0,
        }
    }
    session.save()
    review = reverse("flow_policy_review", args=["forged"])
    for action in ("link", "new"):
        res = client.post(
            review,
            {
                "action": action,
                "slot": 0,
                "policy_id": existing.pk,
                "candidates": str(existing.pk),
            },
        )
        assert (
            res.status_code == 403
            and "нет права создавать полисы" in res.content.decode()
        )
    admin_url = reverse("admin:policies_policy_add") + "?flow_draft=forged"
    res = client.post(admin_url, {"_flow_link": str(existing.pk)})
    assert (
        res.status_code == 403 and "нет права создавать полисы" in res.content.decode()
    )
    assert not FlowPolicySource.objects.exists() and not FlowPolicyLink.objects.exists()
    assert Policy.objects.count() == 1 and existing.payment_schedule.count() == 0


def test_existing_native_editor_can_link_without_new_grant(
    client, django_user_model, source, policy_factory
):
    editor = _local_user(
        django_user_model,
        "polis-existing-editor",
        [
            "add_policy",
            "change_policy",
            "view_policy",
            "add_paymentschedule",
            "change_paymentschedule",
        ],
    )
    assert not editor.has_perm("policies.link_flow_policy")
    existing = policy_factory(dfa_number=source["dfa_number"])
    client.force_login(editor)
    review = open_review(client, source)
    assert client.get(review).context["can_link"]
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        res = client.post(
            review,
            {
                "action": "link",
                "slot": 0,
                "policy_id": existing.pk,
                "candidates": str(existing.pk),
            },
        )
    assert res.url == reverse("policies:detail", args=[existing.pk])
    assert (
        FlowPolicyLink.objects.get().created_by == editor
        and Policy.objects.count() == 1
    )


def test_add_only_without_view_right_creates_under_own_polis_identity(
    client, django_user_model, source
):
    writer = _local_user(
        django_user_model, "polis-operator", ["add_policy", "add_paymentschedule"]
    )
    assert not writer.has_perm("policies.view_policy")
    client.force_login(writer)
    url = open_review(client, source)
    assert "flow_draft=" in url
    values = admin_post_values(client, url)
    with patch(
        "apps.policies.flow_views.flow_client.fetch_snapshot", return_value=source
    ):
        assert client.post(url, values).status_code == 302
    link = FlowPolicyLink.objects.get()
    assert link.created_by_id == writer.pk and link.policy.payment_schedule.count() == 2
    # Этот оператор может создать другой договор по ДФА, но не привязать прежний.
    other = dict(source, summary_id=source["summary_id"] + 1)
    review = open_review(client, other)
    assert not client.get(review).context["can_link"]
    response = client.post(
        review,
        {
            "action": "link",
            "slot": 0,
            "policy_id": link.policy_id,
            "candidates": str(link.policy_id),
        },
    )
    assert (
        response.status_code == 403
        and "нет права связывать" in response.content.decode()
    )
    assert FlowPolicyLink.objects.count() == 1
