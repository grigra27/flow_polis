from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone


@pytest.mark.django_db
def test_week_status_filters_upcoming_seven_days(
    client, admin_user, policy_factory, payment_schedule_factory
):
    today = timezone.localdate()
    policy = policy_factory(
        start_date=today - timedelta(days=120),
        end_date=today + timedelta(days=400),
    )

    # Даты взносов в рамках года строго возрастают, номера уникальны.
    overdue = payment_schedule_factory(
        policy=policy, due_date=today - timedelta(days=1), installment_number=1
    )
    inside_today = payment_schedule_factory(
        policy=policy, due_date=today, installment_number=2
    )
    paid = payment_schedule_factory(
        policy=policy,
        due_date=today + timedelta(days=2),
        paid_date=today,
        installment_number=3,
    )
    inside_edge = payment_schedule_factory(
        policy=policy, due_date=today + timedelta(days=7), installment_number=4
    )
    outside = payment_schedule_factory(
        policy=policy, due_date=today + timedelta(days=8), installment_number=5
    )

    client.force_login(admin_user)
    response = client.get(reverse("policies:payments"), {"status": "week"})

    assert response.status_code == 200
    payments = list(response.context["payments"])
    assert inside_today in payments
    assert inside_edge in payments
    assert outside not in payments
    assert paid not in payments
    assert overdue not in payments
    assert response.context["selected_status"] == "week"


@pytest.mark.django_db
def test_week_status_excludes_inactive_policies(
    client, admin_user, policy_factory, payment_schedule_factory
):
    today = timezone.localdate()
    inactive = policy_factory(policy_number="INACTIVE-W", policy_active=False)
    payment_schedule_factory(
        policy=inactive, due_date=today + timedelta(days=2), amount=Decimal("100")
    )

    client.force_login(admin_user)
    response = client.get(reverse("policies:payments"), {"status": "week"})

    assert response.status_code == 200
    assert list(response.context["payments"]) == []
