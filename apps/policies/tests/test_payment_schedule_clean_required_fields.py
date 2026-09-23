"""
P2-01 (2026-09-23): PaymentSchedule.clean() built Q(year_number__lt=None)
whenever year_number/installment_number were missing, raising a raw
ValueError that got swallowed by a broad `except Exception`, logged as an
ERROR traceback plus a WARNING ("policy 526", 2026-09-14). The fields are
required at the DB level (PositiveSmallIntegerField, not null) — full_clean()
already rejects a missing value via clean_fields() before clean() ever
runs, so no bad data could actually reach the database (confirmed empty on
production: 0 rows with either column NULL). The fix is a cheap early
return, not a data-integrity gap.

Two things are pinned down here:
  (a) missing year_number/installment_number -> ValidationError, not
      ValueError, and nothing gets saved; no ERROR-level traceback either;
  (b) the early return does NOT use `pk` as a guard — a brand-new,
      unsaved (pk=None) PaymentSchedule still gets its date-sequence
      checked against the previous payment, both when valid and invalid.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.policies.models import PaymentSchedule


@pytest.mark.django_db
def test_missing_year_number_raises_validation_error_not_value_error(
    policy_factory,
):
    policy = policy_factory()
    payment = PaymentSchedule(
        policy=policy,
        year_number=None,
        installment_number=1,
        due_date=date.today(),
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    with pytest.raises(ValidationError) as exc_info:
        payment.full_clean()

    assert "year_number" in exc_info.value.message_dict


@pytest.mark.django_db
def test_missing_installment_number_raises_validation_error_not_value_error(
    policy_factory,
):
    policy = policy_factory()
    payment = PaymentSchedule(
        policy=policy,
        year_number=1,
        installment_number=None,
        due_date=date.today(),
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    with pytest.raises(ValidationError) as exc_info:
        payment.full_clean()

    assert "installment_number" in exc_info.value.message_dict


@pytest.mark.django_db
def test_missing_year_number_is_not_saved_and_logs_no_error(policy_factory, caplog):
    policy = policy_factory()
    payment = PaymentSchedule(
        policy=policy,
        year_number=None,
        installment_number=1,
        due_date=date.today(),
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    with caplog.at_level(logging.WARNING, logger="apps.policies.models"):
        with pytest.raises(ValidationError):
            payment.save()  # save() calls full_clean() first

    assert not PaymentSchedule.objects.filter(policy=policy).exists()
    # The old broad `except Exception` path used to log an ERROR traceback
    # plus a WARNING ("Skipping date validation... Manual review
    # recommended") for exactly this case — the early return means clean()
    # never reaches that except block at all now.
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    assert not any("Manual review recommended" in r.message for r in caplog.records)


@pytest.mark.django_db
def test_new_unsaved_payment_pk_none_still_validates_date_sequence(
    policy_factory,
):
    """(b): the guard must not treat pk=None as 'skip validation' — a
    brand-new record with an invalid date sequence must still be rejected."""
    policy = policy_factory()
    first_due = date.today()
    PaymentSchedule.objects.create(
        policy=policy,
        year_number=1,
        installment_number=1,
        due_date=first_due,
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    # Second installment due on/before the first -> invalid sequence.
    second = PaymentSchedule(
        policy=policy,
        year_number=1,
        installment_number=2,
        due_date=first_due,  # not later than the previous payment
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    assert second.pk is None
    with pytest.raises(ValidationError) as exc_info:
        second.full_clean()
    assert "due_date" in exc_info.value.message_dict


@pytest.mark.django_db
def test_new_unsaved_payment_pk_none_with_valid_sequence_saves_cleanly(
    policy_factory,
):
    """(b), positive case: a valid brand-new record must pass and persist —
    proving the sequence check actually ran rather than being silently
    skipped for pk=None."""
    policy = policy_factory()
    first_due = date.today()
    PaymentSchedule.objects.create(
        policy=policy,
        year_number=1,
        installment_number=1,
        due_date=first_due,
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    second = PaymentSchedule(
        policy=policy,
        year_number=1,
        installment_number=2,
        due_date=first_due + timedelta(days=30),
        amount=Decimal("100.00"),
        insurance_sum=Decimal("1000.00"),
    )

    assert second.pk is None
    second.save()  # must not raise

    assert PaymentSchedule.objects.filter(
        policy=policy, year_number=1, installment_number=2
    ).exists()
