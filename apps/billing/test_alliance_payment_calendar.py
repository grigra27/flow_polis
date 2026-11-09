"""Calendar regressions in the real Alliance draft, without sending email."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils.html import strip_tags

from apps.billing.models import BillingPeriod, BillingTask
from apps.clients.models import Client
from apps.communications.models import OutboundEmail
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("deadline", "alliance_date"),
    [
        (date(2024, 5, 2), "27.04.2024"),
        (date(2025, 1, 9), "28.12.2024"),
        (date(2025, 11, 5), "01.11.2025"),
        (date(2026, 1, 12), "30.12.2025"),
        (date(2026, 5, 12), "08.05.2026"),
        (date(2027, 2, 24), "20.02.2027"),
    ],
    ids=lambda value: value.isoformat() if isinstance(value, date) else value,
)
def test_alliance_draft_uses_production_calendar_without_changing_payment(
    deadline, alliance_date
):
    client = Client.objects.create(client_name="Календарный тест")
    insurer = Insurer.objects.create(insurer_name="Тестовая СК")
    branch = Branch.objects.create(branch_name="Тестовый филиал")
    insurance_type = InsuranceType.objects.create(name="КАСКО (календарь)")
    policy = Policy.objects.create(
        policy_number="CALENDAR-001",
        dfa_number="DFA-CALENDAR-001",
        client=client,
        insurer=insurer,
        branch=branch,
        insurance_type=insurance_type,
        property_description="Тестовый автомобиль",
        start_date=deadline - timedelta(days=365),
        end_date=deadline + timedelta(days=365),
    )
    payment = PaymentSchedule.objects.create(
        policy=policy,
        year_number=2,
        installment_number=1,
        due_date=deadline,
        insurance_sum=Decimal("1000000.00"),
        amount=Decimal("50000.00"),
    )
    period = BillingPeriod.objects.create(year=deadline.year, month=deadline.month)
    request_deadline = deadline - timedelta(days=15)
    task = BillingTask.objects.create(
        period=period,
        payment_schedule=payment,
        invoice_request_deadline=request_deadline,
    )

    text = task.build_alliance_letter_text()
    html = task.build_alliance_letter_html()

    assert f"Оплатить до: {alliance_date}" in text.splitlines()
    assert f"Просим оплатить счет до {alliance_date} включительно." in text
    assert f"Оплатить до: {alliance_date}" in strip_tags(html)
    assert f"Дата платежа по договору: {deadline:%d.%m.%Y}" in task.build_letter_text()
    payment.refresh_from_db()
    task.refresh_from_db()
    assert payment.due_date == deadline
    assert task.invoice_request_deadline == request_deadline
    assert task.status == BillingTask.STATUS_TO_REQUEST
    assert OutboundEmail.objects.count() == 0
