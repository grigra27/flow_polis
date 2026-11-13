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
