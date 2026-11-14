"""Денежный расчёт и единый критерий индивидуальной КВ."""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def commission_amount(amount, percent):
    return (Decimal(amount) * Decimal(percent) / Decimal("100")).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def payment_base_rate(payment):
    rate = payment.commission_rate
    if rate is None:
        return None
    policy = payment.policy
    if (
        rate.insurer_id != policy.insurer_id
        or rate.insurance_type_id != policy.insurance_type_id
    ):
        return None
    return rate


def expected_commission(payment):
    rate = payment_base_rate(payment)
    if rate is None or payment.amount is None:
        return None
    return commission_amount(payment.amount, rate.kv_percent)


def is_nonstandard_commission(payment):
    expected = expected_commission(payment)
    if expected is None or payment.kv_rub is None or not payment.amount:
        return False
    return abs(payment.kv_rub - expected) > CENT
