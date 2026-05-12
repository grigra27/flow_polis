from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import BillingTask
from apps.billing.services import sync_period
from apps.clients.models import Client
from apps.communications.models import (
    EmailDeliveryAttempt,
    OutboundEmail,
    OutboundEmailRecipient,
)
from apps.communications.providers.base import SendResult
from apps.communications.services import (
    CommunicationsConfigurationError,
    CommunicationsQueueError,
    CommunicationsSendError,
    create_outbound_email,
    queue_outbound_email,
    retry_outbound_email,
    send_outbound_email_now,
)
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy


@pytest.fixture
def billing_task(db):
    client = Client.objects.create(client_name="ООО Лизингополучатель")
    policyholder = Client.objects.create(client_name="ООО Страхователь")
    insurer = Insurer.objects.create(insurer_name="Тестовая страховая")
    branch = Branch.objects.create(branch_name="Москва")
    insurance_type = InsuranceType.objects.create(name="КАСКО")
    manager = LeasingManager.objects.create(
        name="Петров",
        full_name="Петров Петр Петрович",
        email="petrov@example.com",
    )
    today = timezone.localdate()
    policy = Policy.objects.create(
        policy_number="POL-COMM-001",
        dfa_number="DFA-COMM-001",
        client=client,
        policyholder=policyholder,
        insurer=insurer,
        property_description="Автомобиль для теста communications",
        start_date=today,
        end_date=today + timedelta(days=365),
        insurance_type=insurance_type,
        branch=branch,
        leasing_manager=manager,
    )
    payment = PaymentSchedule.objects.create(
        policy=policy,
        year_number=2,
        installment_number=1,
        due_date=today + timedelta(days=20),
        insurance_sum=Decimal("1000000.00"),
        amount=Decimal("50000.00"),
    )
    sync_period(payment.due_date.year, payment.due_date.month)
    return BillingTask.objects.get(payment_schedule=payment)


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username="root",
        email="root@example.com",
        password="testpass123",
    )


def _create_email(task, user):
    return create_outbound_email(
        kind=OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        content_object=task,
        subject=task.build_letter_subject(),
        body_text=task.build_letter_text(),
        body_html=task.build_letter_html(),
        to="recipient@example.com",
        created_by=user,
    )


@pytest.mark.django_db
def test_create_outbound_email_adds_recipient_and_technical_code(
    billing_task, superuser
):
    email = _create_email(billing_task, superuser)

    assert email.recipients.filter(
        recipient_type=OutboundEmailRecipient.TYPE_TO,
        address="recipient@example.com",
    ).exists()
    assert f"Код запроса: OP-BILLING-{billing_task.id}" in email.body_text
    assert email.message_id
    assert email.headers["X-Onlinepolis-Email-Kind"] == email.kind


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_EMAIL_ENABLED=False)
def test_queue_outbound_email_requires_enabled_setting(billing_task, superuser):
    email = _create_email(billing_task, superuser)

    with pytest.raises(CommunicationsConfigurationError):
        queue_outbound_email(email, user=superuser)


@pytest.mark.django_db
@override_settings(
    COMMUNICATIONS_EMAIL_ENABLED=True,
    COMMUNICATIONS_SMTP_HOST="smtp.example.com",
    COMMUNICATIONS_SMTP_USERNAME="sender@example.com",
    COMMUNICATIONS_SMTP_PASSWORD="not-a-real-password",  # pragma: allowlist secret
    COMMUNICATIONS_FROM_EMAIL="sender@example.com",
)
def test_queue_outbound_email_marks_queued_and_enqueues_task(
    billing_task, superuser, monkeypatch
):
    queued_ids = []

    from apps.communications import tasks

    monkeypatch.setattr(
        tasks.send_outbound_email,
        "delay",
        lambda email_id: queued_ids.append(email_id),
    )
    email = _create_email(billing_task, superuser)

    with TestCase.captureOnCommitCallbacks(execute=True):
        queue_outbound_email(email, user=superuser)

    email.refresh_from_db()
    assert email.status == OutboundEmail.STATUS_QUEUED
    assert email.sent_by == superuser
    assert queued_ids == [email.id]


@pytest.mark.django_db
@override_settings(BILLING_AUTO_UPDATE_TASK_ON_EMAIL_SENT=True)
def test_send_outbound_email_now_marks_sent_and_updates_billing_status(
    billing_task, superuser, monkeypatch
):
    class Provider:
        def send(self, outbound_email):
            return SendResult(
                success=True,
                provider_message_id=outbound_email.message_id,
                response="ok",
            )

    monkeypatch.setattr(
        "apps.communications.services.get_provider", lambda account: Provider()
    )
    email = _create_email(billing_task, superuser)
    email.status = OutboundEmail.STATUS_QUEUED
    email.sent_by = superuser
    email.save(update_fields=["status", "sent_by", "updated_at"])

    send_outbound_email_now(email.id)

    email.refresh_from_db()
    billing_task.refresh_from_db()
    assert email.status == OutboundEmail.STATUS_SENT
    assert billing_task.status == BillingTask.STATUS_REQUESTED
    assert EmailDeliveryAttempt.objects.filter(
        email=email, status=EmailDeliveryAttempt.STATUS_SENT
    ).exists()


@pytest.mark.django_db
def test_send_outbound_email_now_failure_keeps_billing_status(
    billing_task, superuser, monkeypatch
):
    class Provider:
        def send(self, outbound_email):
            raise RuntimeError("smtp unavailable")

    monkeypatch.setattr(
        "apps.communications.services.get_provider", lambda account: Provider()
    )
    email = _create_email(billing_task, superuser)
    email.status = OutboundEmail.STATUS_QUEUED
    email.sent_by = superuser
    email.save(update_fields=["status", "sent_by", "updated_at"])

    with pytest.raises(CommunicationsSendError):
        send_outbound_email_now(email.id)

    email.refresh_from_db()
    billing_task.refresh_from_db()
    assert email.status == OutboundEmail.STATUS_FAILED
    assert "smtp unavailable" in email.last_error
    assert billing_task.status == BillingTask.STATUS_TO_REQUEST


@pytest.mark.django_db
@override_settings(BILLING_AUTO_UPDATE_TASK_ON_EMAIL_SENT=False)
def test_send_does_not_change_billing_status_when_flag_disabled(
    billing_task, superuser, monkeypatch
):
    """При выключенном флаге успешная отправка не меняет BillingTask.status,
    но email всё равно переходит в sent и попадает в историю."""

    class Provider:
        def send(self, outbound_email):
            return SendResult(success=True, provider_message_id="", response="ok")

    monkeypatch.setattr(
        "apps.communications.services.get_provider", lambda account: Provider()
    )
    email = _create_email(billing_task, superuser)
    email.status = OutboundEmail.STATUS_QUEUED
    email.sent_by = superuser
    email.save(update_fields=["status", "sent_by", "updated_at"])

    send_outbound_email_now(email.id)

    email.refresh_from_db()
    billing_task.refresh_from_db()
    assert email.status == OutboundEmail.STATUS_SENT
    assert billing_task.status == BillingTask.STATUS_TO_REQUEST


@pytest.mark.django_db
@override_settings(BILLING_AUTO_UPDATE_TASK_ON_EMAIL_SENT=True)
def test_insurer_request_does_not_retreat_status_for_advanced_task(
    billing_task, superuser, monkeypatch
):
    """Если задача уже в sent_to_leasing, успешная отправка письма в СК
    не должна откатывать статус назад в requested."""
    billing_task.status = BillingTask.STATUS_SENT_TO_LEASING
    billing_task.save(update_fields=["status", "updated_at"])

    class Provider:
        def send(self, outbound_email):
            return SendResult(success=True, provider_message_id="", response="ok")

    monkeypatch.setattr(
        "apps.communications.services.get_provider", lambda account: Provider()
    )
    email = _create_email(billing_task, superuser)
    email.status = OutboundEmail.STATUS_QUEUED
    email.sent_by = superuser
    email.save(update_fields=["status", "sent_by", "updated_at"])

    send_outbound_email_now(email.id)

    billing_task.refresh_from_db()
    assert billing_task.status == BillingTask.STATUS_SENT_TO_LEASING


@pytest.mark.django_db
def test_create_outbound_email_rejects_recent_duplicate(billing_task, superuser):
    _create_email(billing_task, superuser)

    with pytest.raises(CommunicationsQueueError):
        _create_email(billing_task, superuser)


@pytest.mark.django_db
def test_retry_outbound_email_re_enqueues_failed_message(
    billing_task, superuser, monkeypatch
):
    queued_ids = []
    from apps.communications import tasks

    monkeypatch.setattr(
        tasks.send_outbound_email,
        "delay",
        lambda email_id: queued_ids.append(email_id),
    )
    email = _create_email(billing_task, superuser)
    email.status = OutboundEmail.STATUS_FAILED
    email.last_error = "boom"
    email.save(update_fields=["status", "last_error", "updated_at"])

    with override_settings(
        COMMUNICATIONS_EMAIL_ENABLED=True,
        COMMUNICATIONS_SMTP_HOST="smtp.example.com",
        COMMUNICATIONS_SMTP_USERNAME="sender@example.com",
        COMMUNICATIONS_SMTP_PASSWORD="not-a-real-password",  # pragma: allowlist secret
        COMMUNICATIONS_FROM_EMAIL="sender@example.com",
    ), TestCase.captureOnCommitCallbacks(execute=True):
        retry_outbound_email(email, user=superuser)

    email.refresh_from_db()
    assert email.status == OutboundEmail.STATUS_QUEUED
    assert email.last_error == ""
    assert queued_ids == [email.id]


@pytest.mark.django_db
@override_settings(
    COMMUNICATIONS_EMAIL_ENABLED=True,
    COMMUNICATIONS_SMTP_HOST="smtp.example.com",
    COMMUNICATIONS_SMTP_USERNAME="sender@example.com",
    COMMUNICATIONS_SMTP_PASSWORD="not-a-real-password",  # pragma: allowlist secret
    COMMUNICATIONS_FROM_EMAIL="sender@example.com",
)
def test_retry_outbound_email_rejects_non_failed_email(billing_task, superuser):
    email = _create_email(billing_task, superuser)
    # Письмо в статусе draft не подлежит retry.

    with pytest.raises(CommunicationsQueueError):
        retry_outbound_email(email, user=superuser)
