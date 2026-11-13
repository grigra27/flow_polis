from datetime import timedelta

import pytest
from auditlog.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingPeriod, BillingTask


@pytest.fixture
def operator(db):
    def create(*permissions, staff=True):
        user = User.objects.create_user(username="operator", is_staff=staff)
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="policies", codename__in=permissions
            )
        )
        return user

    return create


def date_url(payment, field="paid_date", policy_id=None):
    return reverse(
        "policies:update_payment_date",
        args=[policy_id or payment.policy_id, payment.pk, field],
    )


@pytest.mark.django_db
def test_payment_edit_changes_only_selected_date_and_audits_actor(
    client, operator, sample_payment
):
    payment = sample_payment
    editor = operator("change_paymentschedule")
    client.force_login(editor)
    today = timezone.localdate().isoformat()
    period = BillingPeriod.objects.create(
        year=payment.due_date.year, month=payment.due_date.month
    )
    task = BillingTask.objects.create(
        period=period,
        payment_schedule=payment,
        invoice_request_deadline=payment.due_date,
    )
    payload = {"value": today, "original": "", "amount": "1", "insurer_date": today}
    assert client.post(date_url(payment), payload).status_code == 204
    assert not BillingTask.objects.filter(pk=task.pk).exists()
    assert client.post(date_url(payment), payload).status_code == 204
    payment.refresh_from_db()
    assert payment.amount == 5000 and payment.insurer_date is None
    assert payment.paid_date.isoformat() == today
    entries = LogEntry.objects.get_for_object(payment).filter(
        action=LogEntry.Action.UPDATE
    )
    assert entries.count() == 1
    assert entries[0].actor_id == editor.pk
    assert entries[0].changes["paid_date"][1] == today
    assert "amount" not in entries[0].changes
    stale = client.post(date_url(payment), {"original": "", "value": ""})
    assert stale.status_code == 409
    assert (
        client.post(date_url(payment), {"original": today, "value": ""}).status_code
        == 204
    )
    payment.refresh_from_db()
    assert payment.paid_date is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "staff,permission", [(False, "change_paymentschedule"), (True, "change_policy")]
)
def test_date_actions_require_staff_and_payment_permission(
    client, operator, sample_payment, staff, permission
):
    url = date_url(sample_payment)
    assert client.post(url).status_code == 302
    client.force_login(operator(permission, staff=staff))
    card = client.get(reverse("policies:detail", args=[sample_payment.policy_id]))
    assert "data-date-url=" not in card.content.decode()
    assert client.post(url, {"value": "", "original": ""}).status_code == 403


@pytest.mark.django_db
def test_date_edit_checks_policy_field_and_method(
    client, operator, sample_payment, policy_factory
):
    client.force_login(operator("change_paymentschedule"))
    payload = {"value": "", "original": ""}
    assert client.get(date_url(sample_payment)).status_code == 405
    policy = sample_payment.policy
    other = policy_factory(
        insurance_type=policy.insurance_type,
        insurer=policy.insurer,
        branch=policy.branch,
    )
    assert (
        client.post(date_url(sample_payment, policy_id=other.pk), payload).status_code
        == 404
    )
    assert client.post(date_url(sample_payment, "amount"), payload).status_code == 400
    assert (
        client.post(
            date_url(sample_payment), {"value": "broken", "original": ""}
        ).status_code
        == 422
    )


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["paid_date", "insurer_date"])
def test_date_order_at_both_neighbors(
    client, operator, sample_policy, payment_schedule_factory, field
):
    client.force_login(operator("change_paymentschedule"))
    today = timezone.localdate()
    payments = []
    for number in (1, 2, 3):
        date = today + timedelta(days=number)
        payments.append(
            payment_schedule_factory(
                policy=sample_policy,
                installment_number=number,
                due_date=date,
                **{field: date if number != 2 else None}
            )
        )
    url = date_url(payments[1], field)
    for neighbor in (payments[0], payments[2]):
        invalid = client.post(
            url, {"value": neighbor.due_date.isoformat(), "original": ""}
        )
        assert invalid.status_code == 422
        assert (
            "взноса" in invalid.json()["error"] or "платежа" in invalid.json()["error"]
        )
    assert (
        client.post(
            url, {"value": payments[1].due_date.isoformat(), "original": ""}
        ).status_code
        == 204
    )
    payments[1].refresh_from_db()
    assert getattr(payments[1], field) == payments[1].due_date


def policy_field_url(policy, field):
    return reverse("policies:update_policy_field", args=[policy.pk, field])


@pytest.mark.django_db
def test_empty_policy_note_permission_audit_and_conflict(
    client, operator, sample_policy
):
    policy = sample_policy
    policy.info3 = policy.info4 = ""
    policy.save()
    editor = operator("change_policy")
    client.force_login(editor)
    card = client.get(reverse("policies:detail", args=[policy.pk])).content.decode()
    assert "Добавить заметку" in card and "Изменить отметку" in card
    assert "data-date-url=" not in card
    note = policy_field_url(policy, "info3")
    text = "Первая строка\r\nВторая & <проверка>"
    assert (
        client.post(
            note, {"original": "", "value": text, "policy_uploaded": "yes"}
        ).status_code
        == 204
    )
    policy.refresh_from_db()
    assert policy.info3 == text.replace("\r\n", "\n") and not policy.policy_uploaded
    log = (
        LogEntry.objects.get_for_object(policy)
        .filter(actor=editor, action=LogEntry.Action.UPDATE)
        .get()
    )
    assert log.changes["info3"] == ["", policy.info3]
    assert (
        client.post(note, {"original": "", "value": "Устаревшее значение"}).status_code
        == 409
    )
    assert client.post(note, {"original": text, "value": ""}).status_code == 204
    policy.refresh_from_db()
    assert policy.info3 == ""


@pytest.mark.django_db
def test_upload_mark_is_explicit_idempotent_and_separate(
    client, operator, sample_policy
):
    policy = sample_policy
    editor = operator("change_policy")
    client.force_login(editor)
    url = policy_field_url(policy, "policy_uploaded")
    old_note = policy.info3
    assert client.get(url).status_code == 405
    assert client.post(url, {"original": "no", "value": "maybe"}).status_code == 422
    assert client.post(url, {"original": "no"}).status_code == 400
    assert (
        client.post(
            policy_field_url(policy, "policy_number"),
            {"original": "", "value": "OTHER"},
        ).status_code
        == 400
    )
    for _ in range(2):
        assert (
            client.post(
                url, {"original": "no", "value": "yes", "info3": ""}
            ).status_code
            == 204
        )
    policy.refresh_from_db()
    assert policy.policy_uploaded and policy.info3 == old_note
    log = (
        LogEntry.objects.get_for_object(policy)
        .filter(actor=editor, action=LogEntry.Action.UPDATE)
        .get()
    )
    assert "policy_uploaded" in log.changes and "info3" not in log.changes
    assert client.post(url, {"original": "no", "value": "no"}).status_code == 409
    assert client.post(url, {"original": "yes", "value": "no"}).status_code == 204
    policy.refresh_from_db()
    assert not policy.policy_uploaded


@pytest.mark.django_db
@pytest.mark.parametrize(
    "staff,permission", [(False, "change_policy"), (True, "change_paymentschedule")]
)
def test_policy_controls_require_policy_permission(
    client, operator, sample_payment, staff, permission
):
    policy = sample_payment.policy
    client.force_login(operator(permission, staff=staff))
    card = client.get(reverse("policies:detail", args=[policy.pk])).content.decode()
    assert "Изменить отметку" not in card and "Изменить заметку" not in card
    assert ("data-date-url=" in card) is staff
    for field in ("info3", "policy_uploaded"):
        assert (
            client.post(
                policy_field_url(policy, field), {"original": "", "value": "yes"}
            ).status_code
            == 403
        )
