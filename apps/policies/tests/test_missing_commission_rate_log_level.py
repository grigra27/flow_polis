"""
P2-02 (2026-09-23): a missing CommissionRate for a given insurer/insurance_type
pair is often a legitimate, permanent business state — no contract with that
insurer for that line (confirmed on production for insurer=15 "Чулпан" /
insurance_type=1 "КАСКО") — not a data-completeness bug to silently work
around. The fix here is narrow: the signal must not log it as WARNING, which
reads as an incident and can trip log-based alerting for a normal condition.
"""
import logging

import pytest


@pytest.mark.django_db
def test_missing_commission_rate_logs_info_not_warning(
    payment_schedule_factory, caplog
):
    with caplog.at_level(logging.INFO, logger="apps.policies.signals"):
        # policy_factory (invoked implicitly) creates a fresh insurer +
        # insurance_type pair — no CommissionRate exists for it.
        payment_schedule_factory()

    relevant = [r for r in caplog.records if "commission rate" in r.message.lower()]
    assert relevant, "expected a log record about the missing commission rate"
    assert all(
        r.levelname != "WARNING" for r in relevant
    ), f"missing CommissionRate must not log at WARNING: {[r.message for r in relevant]}"
    assert any(
        r.levelname == "INFO" for r in relevant
    ), f"expected an INFO record, got: {[(r.levelname, r.message) for r in relevant]}"


@pytest.mark.django_db
def test_missing_commission_rate_still_reported_with_context(
    payment_schedule_factory, caplog
):
    """Downgrading to INFO must not lose the diagnostic content — policy id,
    insurer id and insurance_type id should stay visible for anyone actually
    reviewing why a given payment has no commission rate."""
    with caplog.at_level(logging.INFO, logger="apps.policies.signals"):
        payment = payment_schedule_factory()

    messages = [
        r.message for r in caplog.records if "commission rate" in r.message.lower()
    ]
    assert messages
    combined = " ".join(messages)
    assert str(payment.policy_id) in combined
    assert str(payment.policy.insurer_id) in combined
    assert str(payment.policy.insurance_type_id) in combined
