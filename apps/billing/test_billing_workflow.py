from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingTask, BillingTaskEvent
from apps.billing.services import (
    build_period_options,
    preload_periods,
    sync_period,
    update_task,
)
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy


@pytest.fixture
def billing_payment(db):
    client = Client.objects.create(client_name="ООО Лизингополучатель")
    policyholder = Client.objects.create(client_name="ООО Страхователь")
    insurer = Insurer.objects.create(insurer_name="Тестовая страховая")
    branch = Branch.objects.create(branch_name="Москва")
    insurance_type = InsuranceType.objects.create(name="КАСКО")
    manager = LeasingManager.objects.create(
        name="Иванов",
        full_name="Иванов Иван Иванович",
        email="ivanov@example.com",
    )

    today = timezone.localdate()
    due_date = today + timedelta(days=25)
    policy = Policy.objects.create(
        policy_number="POL-001",
        dfa_number="DFA-001",
        client=client,
        policyholder=policyholder,
        insurer=insurer,
        property_description="Автомобиль тестовый",
        start_date=today,
        end_date=today + timedelta(days=365),
        insurance_type=insurance_type,
        branch=branch,
        leasing_manager=manager,
    )
    return PaymentSchedule.objects.create(
        policy=policy,
        year_number=1,
        installment_number=1,
        due_date=due_date,
        insurance_sum=Decimal("1000000.00"),
        amount=Decimal("50000.00"),
    )


@pytest.mark.django_db
def test_preload_periods_does_not_create_tasks_but_counts_unsynced_payments(
    billing_payment,
):
    periods = preload_periods(today=timezone.localdate())

    assert BillingTask.objects.count() == 0

    payment_period = next(
        period
        for period in periods
        if period.year == billing_payment.due_date.year
        and period.month == billing_payment.due_date.month
    )
    period_options = build_period_options(periods, payment_period)
    payment_option = next(
        option for option in period_options if option.period.id == payment_period.id
    )

    assert payment_option.total == 1
    assert payment_option.to_request == 1


@pytest.mark.django_db
def test_sync_period_creates_task_for_unpaid_active_payment(billing_payment):
    period = sync_period(billing_payment.due_date.year, billing_payment.due_date.month)

    task = BillingTask.objects.get(payment_schedule=billing_payment)

    assert task.period == period
    assert task.status == BillingTask.STATUS_TO_REQUEST
    assert task.invoice_request_deadline == billing_payment.due_date - timedelta(
        weeks=2
    )
    assert BillingTaskEvent.objects.filter(
        task=task, event_type=BillingTaskEvent.EVENT_CREATED
    ).exists()
    assert "Просим выставить счет" in task.build_letter_text()
    assert "DFA-001" in task.build_letter_text()


@pytest.mark.django_db
def test_update_task_advances_status_and_records_events(billing_payment):
    user = User.objects.create_superuser(username="admin", password="testpass123")
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)

    update_task(
        task,
        user,
        new_status=BillingTask.STATUS_REQUESTED,
        comment="Запрос отправлен через Outlook",
    )
    task.refresh_from_db()

    assert task.status == BillingTask.STATUS_REQUESTED
    assert task.responsible == user
    assert task.requested_at is not None
    assert task.comment == "Запрос отправлен через Outlook"

    update_task(task, user, new_status=BillingTask.STATUS_SENT_TO_LEASING)
    task.refresh_from_db()

    assert task.status == BillingTask.STATUS_SENT_TO_LEASING
    assert task.sent_to_leasing_at is not None
    assert (
        BillingTaskEvent.objects.filter(
            task=task, event_type=BillingTaskEvent.EVENT_STATUS_CHANGED
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_comment_update_does_not_create_history_event(billing_payment):
    user = User.objects.create_superuser(username="notes_admin", password="testpass123")
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)
    initial_event_count = task.events.count()

    update_task(task, user, comment="Рабочая заметка без события в истории")
    task.refresh_from_db()

    assert task.comment == "Рабочая заметка без события в истории"
    assert task.events.count() == initial_event_count


@pytest.mark.django_db
def test_scheduled_payments_pages_require_admin_access(client, billing_payment):
    regular_user = User.objects.create_user(username="regular", password="testpass123")
    client.force_login(regular_user)

    response = client.get(reverse("policies:scheduled_payments"))

    assert response.status_code == 302
    assert reverse("accounts:access_denied") in response["Location"]

    response = client.get(reverse("policies:prolongation"))

    assert response.status_code == 302
    assert reverse("accounts:access_denied") in response["Location"]

    admin_user = User.objects.create_user(
        username="billing_admin",
        password="testpass123",
        is_staff=True,
    )
    client.force_login(admin_user)

    response = client.get(reverse("policies:scheduled_payments"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Очередные взносы" in content
    assert "Сбросить" in content
    assert "insurer-with-logo" in content

    task = BillingTask.objects.get(payment_schedule=billing_payment)
    response = client.get(reverse("policies:scheduled_payment_task", args=[task.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Текст письма в СК" in content
    assert reverse("policies:detail", args=[billing_payment.policy.id]) in content

    response = client.get(reverse("policies:prolongation"))

    assert response.status_code == 200
    assert "Пролонгация" in response.content.decode("utf-8")
    assert "Страница находится в разработке." in response.content.decode("utf-8")


@pytest.mark.django_db
def test_task_history_displays_user_full_name(client, billing_payment):
    user = User.objects.create_superuser(
        username="history_admin",
        password="testpass123",
        first_name="Иван",
        last_name="Петров",
    )
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)
    update_task(task, user, new_status=BillingTask.STATUS_REQUESTED)

    client.force_login(user)
    response = client.get(reverse("policies:scheduled_payment_task", args=[task.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Иван Петров" in content


@pytest.mark.django_db
def test_task_status_form_updates_status_only(client, billing_payment):
    user = User.objects.create_superuser(
        username="status_only_admin",
        password="testpass123",
    )
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)
    update_task(task, user, comment="Комментарий должен остаться")

    client.force_login(user)
    detail_url = reverse("policies:scheduled_payment_task", args=[task.pk])
    response = client.post(
        reverse("policies:scheduled_payment_task_update", args=[task.pk]),
        {
            "action": "status",
            "status": BillingTask.STATUS_REQUESTED,
            "next": detail_url,
        },
    )

    assert response.status_code == 302
    assert response.url == detail_url

    task.refresh_from_db()
    assert task.status == BillingTask.STATUS_REQUESTED
    assert task.comment == "Комментарий должен остаться"
    assert task.events.filter(event_type=BillingTaskEvent.EVENT_STATUS_CHANGED).exists()


@pytest.mark.django_db
def test_task_comment_form_updates_comment_without_status_change(
    client, billing_payment
):
    user = User.objects.create_superuser(
        username="comment_only_admin",
        password="testpass123",
    )
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)
    initial_status = task.status
    initial_event_count = task.events.count()

    client.force_login(user)
    detail_url = reverse("policies:scheduled_payment_task", args=[task.pk])
    response = client.post(
        reverse("policies:scheduled_payment_task_update", args=[task.pk]),
        {
            "action": "comment",
            "comment": "Отдельное сохранение комментария",
            "next": detail_url,
        },
        follow=True,
    )

    assert response.status_code == 200
    page_content = response.content.decode("utf-8")
    assert "Отдельное сохранение комментария" in page_content
    assert "Изменить комментарий" in page_content

    task.refresh_from_db()
    assert task.status == initial_status
    assert task.comment == "Отдельное сохранение комментария"
    assert task.events.count() == initial_event_count


@pytest.mark.django_db
def test_payments_page_shows_scheduled_payments_button_only_to_admin(
    client, billing_payment
):
    regular_user = User.objects.create_user(
        username="payments_regular", password="testpass123"
    )
    client.force_login(regular_user)

    response = client.get(f"{reverse('policies:payments')}?status=all")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Очередные взносы" not in content
    assert "Пролонгация" not in content

    admin_user = User.objects.create_user(
        username="payments_admin",
        password="testpass123",
        is_staff=True,
    )
    client.force_login(admin_user)

    response = client.get(f"{reverse('policies:payments')}?status=all")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Очередные взносы" in content
    assert "Пролонгация" in content
    assert reverse("policies:scheduled_payments") in content
    assert reverse("policies:prolongation") in content
