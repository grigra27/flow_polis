"""
Тесты вычисляемого определения «полис в силе» (in-force).

Проверяют `in_force_q`, `Policy.objects.in_force()` и property `is_in_force`:
плановое окончание (end_date), досрочное расторжение (termination_date),
ручной флаг policy_active и срез на произвольную дату (as_of).
"""
from datetime import date, timedelta

import pytest

from apps.policies.models import Policy, in_force_q


pytestmark = [pytest.mark.django_db, pytest.mark.unit]


TODAY = date(2026, 6, 10)


def _ids(qs):
    return set(qs.values_list("id", flat=True))


def test_active_policy_in_window_is_in_force(policy_factory):
    """Полис в плановом окне и с поднятым флагом — в силе."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=10),
        end_date=TODAY + timedelta(days=355),
        policy_active=True,
    )
    assert p.id in _ids(Policy.objects.in_force(TODAY))


def test_expired_policy_is_not_in_force(policy_factory):
    """Полис с прошедшим end_date не в силе, хотя флаг поднят."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=400),
        end_date=TODAY - timedelta(days=1),
        policy_active=True,
    )
    assert p.id not in _ids(Policy.objects.in_force(TODAY))


def test_not_started_policy_is_not_in_force(policy_factory):
    """Ещё не начавшийся полис (start_date в будущем) не в силе."""
    p = policy_factory(
        start_date=TODAY + timedelta(days=5),
        end_date=TODAY + timedelta(days=370),
        policy_active=True,
    )
    assert p.id not in _ids(Policy.objects.in_force(TODAY))


def test_terminated_in_future_is_in_force_until_date(policy_factory):
    """Досрочно расторгнутый: в силе до termination_date, не после."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=30),
        end_date=TODAY + timedelta(days=300),
        policy_active=False,
        termination_date=TODAY + timedelta(days=10),
    )
    assert p.id in _ids(Policy.objects.in_force(TODAY))
    assert p.id not in _ids(Policy.objects.in_force(TODAY + timedelta(days=20)))


def test_terminated_in_past_is_not_in_force(policy_factory):
    """Расторгнутый в прошлом — не в силе сегодня."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=200),
        end_date=TODAY + timedelta(days=160),
        policy_active=False,
        termination_date=TODAY - timedelta(days=5),
    )
    assert p.id not in _ids(Policy.objects.in_force(TODAY))


def test_manually_closed_without_date_is_not_in_force(policy_factory):
    """Снятый флаг без termination_date трактуется как закрытый."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=30),
        end_date=TODAY + timedelta(days=300),
        policy_active=False,
        termination_date=None,
    )
    assert p.id not in _ids(Policy.objects.in_force(TODAY))


def test_historical_snapshot_for_terminated_policy(policy_factory):
    """Срез на прошлую дату: расторгнутый полис был в силе до расторжения."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=200),
        end_date=TODAY + timedelta(days=160),
        policy_active=False,
        termination_date=TODAY - timedelta(days=30),
    )
    past = TODAY - timedelta(days=60)  # до расторжения и внутри окна
    assert p.id in _ids(Policy.objects.in_force(past))
    assert p.id not in _ids(Policy.objects.in_force(TODAY))


def test_historical_snapshot_for_expired_policy(policy_factory):
    """Срез на прошлую дату: ныне истёкший полис был в силе в окне."""
    p = policy_factory(
        start_date=TODAY - timedelta(days=400),
        end_date=TODAY - timedelta(days=10),
        policy_active=True,
    )
    past = TODAY - timedelta(days=200)
    assert p.id in _ids(Policy.objects.in_force(past))
    assert p.id not in _ids(Policy.objects.in_force(TODAY))


def test_in_force_q_with_prefix_filters_payments(
    policy_factory, payment_schedule_factory, insurance_type_factory
):
    """in_force_q с prefix='policy__' фильтрует платежи через связь."""
    from apps.policies.models import PaymentSchedule

    ins_type = insurance_type_factory(name="КАСКО in_force test 1")
    active = policy_factory(
        start_date=TODAY - timedelta(days=10),
        end_date=TODAY + timedelta(days=355),
        policy_active=True,
        insurance_type=ins_type,
    )
    expired = policy_factory(
        start_date=TODAY - timedelta(days=400),
        end_date=TODAY - timedelta(days=1),
        policy_active=True,
        insurance_type=ins_type,
    )
    pay_active = payment_schedule_factory(policy=active)
    payment_schedule_factory(policy=expired)

    in_force_payments = PaymentSchedule.objects.filter(
        in_force_q(TODAY, prefix="policy__")
    )
    assert pay_active.id in _ids(in_force_payments)
    assert in_force_payments.filter(policy=expired).count() == 0


def test_is_in_force_property_matches_manager(policy_factory, insurance_type_factory):
    """Property is_in_force согласуется с менеджером на сегодня."""
    ins_type = insurance_type_factory(name="КАСКО in_force test 2")
    active = policy_factory(
        start_date=date.today() - timedelta(days=10),
        end_date=date.today() + timedelta(days=355),
        policy_active=True,
        insurance_type=ins_type,
    )
    expired = policy_factory(
        start_date=date.today() - timedelta(days=400),
        end_date=date.today() - timedelta(days=1),
        policy_active=True,
        insurance_type=ins_type,
    )
    assert active.is_in_force is True
    assert expired.is_in_force is False
    in_force_ids = _ids(Policy.objects.in_force())
    assert active.id in in_force_ids
    assert expired.id not in in_force_ids
