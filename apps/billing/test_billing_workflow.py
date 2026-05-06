from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingPeriod, BillingTask, BillingTaskEvent
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
        year_number=2,
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
    letter = task.build_letter_text()
    subject = task.build_letter_subject()
    alliance_subject = task.build_alliance_letter_subject()
    assert "Просим выставить счет" in letter
    assert "Просим выставить счет на годовой взнос по договору страхования:" in letter
    assert "DFA-001" in letter
    assert "Страховая сумма" not in letter
    assert "Статус рассрочки" not in letter
    assert "Всего платежей в году" not in letter
    assert "Этот платеж в году" not in letter
    alliance_letter = task.build_alliance_letter_text()
    assert "Год страхования: 2 год страхования" in alliance_letter
    assert "Страховая сумма: 1 000 000,00 руб." in alliance_letter
    assert "Тип взноса: годовой" in alliance_letter
    assert "Страховщик:" not in alliance_letter
    assert "Лизингополучатель:" not in alliance_letter
    assert subject == "Счёт на годовой взнос --- DFA-001 --- Москва --- POL-001"
    assert (
        alliance_subject
        == "СТРАХОВАНИЕ --- счет --- DFA-001 --- Москва --- Тестовая страховая"
    )


@pytest.mark.django_db
def test_letter_contains_installment_metadata_for_installment_plan(billing_payment):
    PaymentSchedule.objects.create(
        policy=billing_payment.policy,
        year_number=billing_payment.year_number,
        installment_number=2,
        due_date=billing_payment.due_date + timedelta(days=30),
        insurance_sum=Decimal("1000000.00"),
        amount=Decimal("25000.00"),
    )

    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)

    letter = task.build_letter_text()
    subject = task.build_letter_subject()
    alliance_subject = task.build_alliance_letter_subject()
    assert "Просим выставить счет на очередной взнос по договору страхования:" in letter
    assert "Статус рассрочки" not in letter
    assert "Всего платежей в году" not in letter
    assert "Этот платеж в году" not in letter
    alliance_letter = task.build_alliance_letter_text()
    assert "Год страхования: 2 год страхования" in alliance_letter
    assert "Тип взноса: рассрочка, платёж 1 из 2" in alliance_letter
    assert "Страховщик:" not in alliance_letter
    assert "Лизингополучатель:" not in alliance_letter
    assert subject == "Счёт на очередной взнос --- DFA-001 --- Москва --- POL-001"
    assert (
        alliance_subject
        == "СТРАХОВАНИЕ --- счет --- DFA-001 --- Москва --- Тестовая страховая"
    )


@pytest.mark.django_db
def test_sync_period_excludes_first_payment_of_first_year_and_cleans_stale_task(
    billing_payment,
):
    excluded_payment = PaymentSchedule.objects.create(
        policy=billing_payment.policy,
        year_number=1,
        installment_number=1,
        due_date=billing_payment.due_date,
        insurance_sum=Decimal("900000.00"),
        amount=Decimal("40000.00"),
    )
    period, _ = BillingPeriod.objects.get_or_create(
        year=excluded_payment.due_date.year,
        month=excluded_payment.due_date.month,
    )
    stale_task = BillingTask.objects.create(
        period=period,
        payment_schedule=excluded_payment,
        invoice_request_deadline=excluded_payment.due_date - timedelta(weeks=2),
    )

    sync_period(period.year, period.month)

    assert not BillingTask.objects.filter(payment_schedule=excluded_payment).exists()
    assert not BillingTask.objects.filter(pk=stale_task.pk).exists()
    assert BillingTask.objects.filter(payment_schedule=billing_payment).exists()


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
def test_scheduled_payments_pages_require_login(client, billing_payment):
    response = client.get(reverse("policies:scheduled_payments"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]

    response = client.get(reverse("policies:prolongation"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]

    regular_user = User.objects.create_user(username="regular", password="testpass123")
    client.force_login(regular_user)

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
    assert "Текст письма в" in content
    assert "Тестовая страховая" in content
    assert "Тема письма" in content
    assert "Счёт на годовой взнос --- DFA-001 --- Москва --- POL-001" in content
    assert (
        "СТРАХОВАНИЕ --- счет --- DFA-001 --- Москва --- Тестовая страховая" in content
    )
    assert "Год страхования: 2 год страхования" in content
    assert reverse("policies:detail", args=[billing_payment.policy.id]) in content

    response = client.get(reverse("policies:prolongation"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Пролонгация" in content
    assert "Страница находится в разработке." in content
    assert (
        f'class="nav-link submenu-tab active" href="{reverse("policies:payments")}"'
        in content
    )
    assert f'class="nav-link active" href="{reverse("policies:list")}"' not in content


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
def test_scheduled_payments_list_displays_task_comment_column(client, billing_payment):
    user = User.objects.create_user(
        username="comment_list_user", password="testpass123"
    )
    period = sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)
    task.comment = "Комментарий для строки списка"
    task.save(update_fields=["comment"])

    client.force_login(user)
    response = client.get(
        reverse("policies:scheduled_payments"),
        {"period": period.code},
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "<th>Комментарии</th>" in content
    assert "<th>Менеджер</th>" not in content
    assert "Комментарий для строки списка" in content


@pytest.mark.django_db
def test_scheduled_payments_supports_multiple_branch_filter(client, billing_payment):
    user = User.objects.create_user(
        username="multi_branch_user", password="testpass123"
    )
    base_policy = billing_payment.policy
    branch_spb = Branch.objects.create(branch_name="Санкт-Петербург")
    branch_ekb = Branch.objects.create(branch_name="Екатеринбург")

    def create_payment_for_branch(suffix, branch):
        policy = Policy.objects.create(
            policy_number=f"POL-MULTI-{suffix}",
            dfa_number=f"DFA-MULTI-{suffix}",
            client=Client.objects.create(client_name=f"ООО Клиент {suffix}"),
            policyholder=Client.objects.create(
                client_name=f"ООО Страхователь {suffix}"
            ),
            insurer=base_policy.insurer,
            property_description=f"Тестовый объект {suffix}",
            start_date=base_policy.start_date,
            end_date=base_policy.end_date,
            insurance_type=base_policy.insurance_type,
            branch=branch,
            leasing_manager=base_policy.leasing_manager,
        )
        return PaymentSchedule.objects.create(
            policy=policy,
            year_number=2,
            installment_number=1,
            due_date=billing_payment.due_date,
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("50000.00"),
        )

    payment_spb = create_payment_for_branch("SPB", branch_spb)
    payment_ekb = create_payment_for_branch("EKB", branch_ekb)
    period = sync_period(billing_payment.due_date.year, billing_payment.due_date.month)

    client.force_login(user)
    response = client.get(
        reverse("policies:scheduled_payments"),
        {
            "period": period.code,
            "branch": [str(base_policy.branch_id), str(branch_spb.id)],
        },
    )

    assert response.status_code == 200
    assert response.context["selected_branches"] == [
        str(base_policy.branch_id),
        str(branch_spb.id),
    ]
    content = response.content.decode("utf-8")
    assert base_policy.policy_number in content
    assert payment_spb.policy.policy_number in content
    assert payment_ekb.policy.policy_number not in content
    assert 'id="branchMultiselect"' in content
    assert 'data-branch-action="all"' in content
    assert 'type="checkbox" name="branch" value="' in content


@pytest.mark.django_db
def test_scheduled_payments_branch_group_shortcuts(client, billing_payment):
    user = User.objects.create_user(
        username="branch_group_user", password="testpass123"
    )
    base_policy = billing_payment.policy
    branch_krasnodar = Branch.objects.create(branch_name="Краснодар")
    branch_pskov = Branch.objects.create(branch_name="Псков")
    branch_spb = Branch.objects.create(branch_name="Санкт-Петербург")
    branch_ekb = Branch.objects.create(branch_name="Екатеринбург")

    def create_payment_for_branch(suffix, branch):
        policy = Policy.objects.create(
            policy_number=f"POL-GRP-{suffix}",
            dfa_number=f"DFA-GRP-{suffix}",
            client=Client.objects.create(client_name=f"ООО Клиент grp {suffix}"),
            policyholder=Client.objects.create(
                client_name=f"ООО Страхователь grp {suffix}"
            ),
            insurer=base_policy.insurer,
            property_description=f"Объект grp {suffix}",
            start_date=base_policy.start_date,
            end_date=base_policy.end_date,
            insurance_type=base_policy.insurance_type,
            branch=branch,
            leasing_manager=base_policy.leasing_manager,
        )
        return PaymentSchedule.objects.create(
            policy=policy,
            year_number=2,
            installment_number=1,
            due_date=billing_payment.due_date,
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("50000.00"),
        )

    payment_krasnodar = create_payment_for_branch("KRD", branch_krasnodar)
    payment_pskov = create_payment_for_branch("PSK", branch_pskov)
    payment_spb = create_payment_for_branch("SPB", branch_spb)
    payment_ekb = create_payment_for_branch("EKB", branch_ekb)
    period = sync_period(billing_payment.due_date.year, billing_payment.due_date.month)

    client.force_login(user)
    response_group_1 = client.get(
        reverse("policies:scheduled_payments"),
        {
            "period": period.code,
            "branch_group": "group1",
        },
    )

    assert response_group_1.status_code == 200
    assert set(response_group_1.context["selected_branches"]) == {
        str(base_policy.branch_id),
        str(branch_krasnodar.id),
        str(branch_pskov.id),
        str(branch_spb.id),
    }
    content_group_1 = response_group_1.content.decode("utf-8")
    assert 'id="branchGroupHidden" value="group1"' in content_group_1
    assert "Шорткаты" in content_group_1
    assert "Кластер 1:" in content_group_1
    assert "Кластер 2:" in content_group_1
    assert "Москва" in content_group_1
    assert "Краснодар" in content_group_1
    assert "Псков" in content_group_1
    assert "Санкт-Петербург" in content_group_1
    assert "Екатеринбург" in content_group_1
    assert base_policy.policy_number in content_group_1
    assert payment_krasnodar.policy.policy_number in content_group_1
    assert payment_pskov.policy.policy_number in content_group_1
    assert payment_spb.policy.policy_number in content_group_1
    assert payment_ekb.policy.policy_number not in content_group_1
    assert "branch_group=group1" in content_group_1

    response_group_2 = client.get(
        reverse("policies:scheduled_payments"),
        {
            "period": period.code,
            "branch_group": "group2",
        },
    )

    assert response_group_2.status_code == 200
    assert response_group_2.context["selected_branches"] == [str(branch_ekb.id)]
    content_group_2 = response_group_2.content.decode("utf-8")
    assert payment_ekb.policy.policy_number in content_group_2
    assert base_policy.policy_number not in content_group_2
    assert payment_krasnodar.policy.policy_number not in content_group_2


@pytest.mark.django_db
def test_task_detail_displays_payment_note(client, billing_payment):
    billing_payment.payment_info = "Примечание к конкретному платежу для карточки."
    billing_payment.save(update_fields=["payment_info"])

    admin_user = User.objects.create_user(
        username="note_admin",
        password="testpass123",
        is_staff=True,
    )
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)

    client.force_login(admin_user)
    response = client.get(reverse("policies:scheduled_payment_task", args=[task.pk]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Примечание к платежу" in content
    assert "Примечание к конкретному платежу для карточки." in content
    assert "Страховая сумма" in content
    assert "1 000 000 ₽" in content
    assert "insurer-with-logo" in content
    assert "branch-with-logo" in content
    assert billing_payment.policy.start_date.strftime("%d.%m.%Y") in content
    assert billing_payment.policy.end_date.strftime("%d.%m.%Y") in content


@pytest.mark.django_db
def test_scheduled_payments_exclude_policy_without_broker_from_list_and_counts(
    client, billing_payment
):
    billing_payment.policy.broker_participation = False
    billing_payment.policy.save(update_fields=["broker_participation"])

    admin_user = User.objects.create_user(
        username="nobroker_admin",
        password="testpass123",
        is_staff=True,
    )
    period, _ = BillingPeriod.objects.get_or_create(
        year=billing_payment.due_date.year,
        month=billing_payment.due_date.month,
    )
    period_options = build_period_options([period], period)
    payment_option = period_options[0]
    assert payment_option.total == 0
    assert payment_option.to_request == 0

    sync_period(period.year, period.month)
    assert not BillingTask.objects.filter(payment_schedule=billing_payment).exists()

    client.force_login(admin_user)

    response = client.get(
        reverse("policies:scheduled_payments"),
        {"period": period.code},
    )
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert billing_payment.policy.policy_number not in content
    assert billing_payment.policy.client.client_name not in content
    assert "Без брокера" not in content
    assert 'title="Без участия брокера"' not in content


@pytest.mark.django_db
def test_task_status_form_updates_status_only(client, billing_payment):
    user = User.objects.create_user(
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
    user = User.objects.create_user(
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
def test_regular_user_can_bulk_update_task_status(client, billing_payment):
    user = User.objects.create_user(
        username="bulk_regular",
        password="testpass123",
    )
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)

    client.force_login(user)
    next_url = reverse("policies:scheduled_payments")
    response = client.post(
        reverse("policies:scheduled_payment_bulk_update"),
        {
            "task_ids": [str(task.id)],
            "status": BillingTask.STATUS_REQUESTED,
            "next": next_url,
        },
    )

    assert response.status_code == 302
    assert response.url == next_url

    task.refresh_from_db()
    assert task.status == BillingTask.STATUS_REQUESTED
    assert task.responsible == user
    assert task.events.filter(event_type=BillingTaskEvent.EVENT_STATUS_CHANGED).exists()


@pytest.mark.django_db
def test_payments_page_shows_scheduled_payments_buttons_to_authenticated_users(
    client, billing_payment
):
    regular_user = User.objects.create_user(
        username="payments_regular", password="testpass123"
    )
    client.force_login(regular_user)

    response = client.get(f"{reverse('policies:payments')}?status=all")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Очередные взносы" in content
    assert "Пролонгация" in content
    assert reverse("policies:scheduled_payments") in content
    assert reverse("policies:prolongation") in content

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


@pytest.mark.django_db
def test_letter_skips_policyholder_line_when_absent(billing_payment):
    billing_payment.policy.policyholder = None
    billing_payment.policy.save(update_fields=["policyholder"])
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)

    letter = task.build_letter_text()

    assert "Страхователь:" not in letter
    assert "Лизингополучатель:" in letter


@pytest.mark.django_db
def test_paid_payment_removes_billing_task(billing_payment):
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    assert BillingTask.objects.filter(payment_schedule=billing_payment).exists()

    billing_payment.paid_date = timezone.localdate()
    billing_payment.save(update_fields=["paid_date"])

    assert not BillingTask.objects.filter(payment_schedule=billing_payment).exists()


@pytest.mark.django_db
def test_due_date_change_moves_task_to_new_period_and_updates_deadline(billing_payment):
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    task = BillingTask.objects.get(payment_schedule=billing_payment)
    original_period_id = task.period_id

    new_due_date = billing_payment.due_date + timedelta(days=45)
    billing_payment.due_date = new_due_date
    billing_payment.save(update_fields=["due_date"])

    task.refresh_from_db()
    assert task.invoice_request_deadline == new_due_date - timedelta(weeks=2)
    assert task.period.year == new_due_date.year
    assert task.period.month == new_due_date.month
    assert task.period_id != original_period_id
    assert task.events.filter(event_type=BillingTaskEvent.EVENT_SYNCED).exists()


@pytest.mark.django_db
def test_inactive_policy_removes_billing_tasks(billing_payment):
    sync_period(billing_payment.due_date.year, billing_payment.due_date.month)
    assert BillingTask.objects.filter(payment_schedule=billing_payment).exists()

    policy = billing_payment.policy
    policy.policy_active = False
    policy.save(update_fields=["policy_active"])

    assert not BillingTask.objects.filter(payment_schedule=billing_payment).exists()


@pytest.mark.django_db
def test_sync_period_skips_archived_period(billing_payment):
    period, _ = BillingPeriod.objects.get_or_create(
        year=billing_payment.due_date.year,
        month=billing_payment.due_date.month,
    )
    period.status = BillingPeriod.STATUS_ARCHIVED
    period.save(update_fields=["status"])

    sync_period(period.year, period.month)

    assert not BillingTask.objects.filter(payment_schedule=billing_payment).exists()
