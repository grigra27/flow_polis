"""
Правила ОСАГО на уровне модели (этап 1).

ОСАГО — обычный Policy с видом страхования, у которого is_osago=True:
один платёж (год 1, платёж 1), без страховой суммы, срок не больше года,
без франшизы, КВ не больше 10% (и в ставке, и в платеже).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.insurers.models import CommissionRate, InsuranceType
from apps.policies.models import PaymentSchedule, Policy, add_years

pytestmark = pytest.mark.unit


@pytest.fixture
def osago_type(db):
    return InsuranceType.objects.create(name="ОСАГО (тест)", is_osago=True)


@pytest.fixture
def kasko_type(db):
    return InsuranceType.objects.create(name="КАСКО (тест)")


@pytest.fixture
def osago_policy(policy_factory, osago_type):
    return policy_factory(
        policy_number="OSAGO-1",
        insurance_type=osago_type,
        start_date=date(2026, 1, 15),
        end_date=date(2027, 1, 14),
        franchise=Decimal("0"),
    )


def make_payment(policy, **kwargs):
    defaults = {
        "year_number": 1,
        "installment_number": 1,
        "due_date": policy.start_date,
        "insurance_sum": None,
        "amount": Decimal("12000"),
        "kv_rub": Decimal("1200"),
    }
    defaults.update(kwargs)
    return PaymentSchedule.objects.create(policy=policy, **defaults)


class TestQuerysets:
    def test_policy_osago_and_without_osago(
        self, policy_factory, osago_policy, kasko_type
    ):
        kasko = policy_factory(policy_number="KASKO-1", insurance_type=kasko_type)

        assert list(Policy.objects.osago()) == [osago_policy]
        assert list(Policy.objects.without_osago()) == [kasko]
        # in_force и фильтры ОСАГО комбинируются (менеджер построен на queryset).
        assert osago_policy not in Policy.objects.in_force(date(2030, 1, 1)).osago()

    def test_payment_osago_and_without_osago(
        self, policy_factory, osago_policy, kasko_type
    ):
        kasko = policy_factory(policy_number="KASKO-1", insurance_type=kasko_type)
        osago_payment = make_payment(osago_policy)
        kasko_payment = make_payment(kasko, insurance_sum=Decimal("1000000"))

        assert list(PaymentSchedule.objects.osago()) == [osago_payment]
        assert list(PaymentSchedule.objects.without_osago()) == [kasko_payment]

    def test_is_osago_property(self, policy_factory, osago_policy, kasko_type):
        assert osago_policy.is_osago is True
        assert (
            policy_factory(policy_number="K", insurance_type=kasko_type).is_osago
            is False
        )


class TestPolicyClean:
    def test_one_year_term_is_valid(self, osago_policy):
        osago_policy.full_clean()

    def test_same_date_next_year_is_tolerated(self, osago_policy):
        osago_policy.end_date = date(2027, 1, 15)
        osago_policy.full_clean()

    def test_short_term_is_valid(self, osago_policy):
        osago_policy.end_date = osago_policy.start_date + timedelta(days=20)
        osago_policy.full_clean()

    def test_longer_than_year_is_rejected(self, osago_policy):
        osago_policy.end_date = date(2027, 1, 16)
        with pytest.raises(ValidationError) as exc:
            osago_policy.full_clean()
        assert "end_date" in exc.value.message_dict

    def test_end_before_start_is_rejected(self, osago_policy):
        osago_policy.end_date = osago_policy.start_date - timedelta(days=1)
        with pytest.raises(ValidationError) as exc:
            osago_policy.full_clean()
        assert "end_date" in exc.value.message_dict

    def test_franchise_is_rejected(self, osago_policy):
        osago_policy.franchise = Decimal("5000")
        with pytest.raises(ValidationError) as exc:
            osago_policy.full_clean()
        assert "franchise" in exc.value.message_dict

    def test_non_osago_keeps_multi_year_and_franchise(self, policy_factory, kasko_type):
        policy = policy_factory(
            insurance_type=kasko_type,
            start_date=date(2026, 1, 1),
            end_date=date(2029, 12, 31),
            franchise=Decimal("10000"),
        )
        policy.full_clean()

    def test_add_years_handles_leap_day(self):
        assert add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)
        assert add_years(date(2026, 1, 15), 1) == date(2027, 1, 15)


class TestPaymentClean:
    def test_single_payment_without_insurance_sum_is_valid(self, osago_policy):
        payment = make_payment(osago_policy)
        assert payment.pk is not None
        assert payment.insurance_sum is None

    def test_second_payment_is_rejected(self, osago_policy):
        make_payment(osago_policy)
        with pytest.raises(ValidationError) as exc:
            make_payment(
                osago_policy,
                installment_number=2,
                due_date=osago_policy.start_date + timedelta(days=30),
            )
        assert "installment_number" in exc.value.message_dict

    def test_second_year_is_rejected(self, osago_policy):
        with pytest.raises(ValidationError) as exc:
            make_payment(osago_policy, year_number=2)
        assert "installment_number" in exc.value.message_dict

    def test_insurance_sum_is_rejected(self, osago_policy):
        with pytest.raises(ValidationError) as exc:
            make_payment(osago_policy, insurance_sum=Decimal("400000"))
        assert "insurance_sum" in exc.value.message_dict

    def test_kv_at_ten_percent_is_valid(self, osago_policy):
        make_payment(osago_policy, amount=Decimal("12000"), kv_rub=Decimal("1200"))

    def test_kv_above_ten_percent_is_rejected(self, osago_policy):
        with pytest.raises(ValidationError) as exc:
            make_payment(
                osago_policy, amount=Decimal("12000"), kv_rub=Decimal("1200.01")
            )
        assert "kv_rub" in exc.value.message_dict

    def test_rules_apply_on_admin_formset_path(self, osago_policy):
        """Флаг formset (H-02) отключает только проверку порядка дат."""
        payment = PaymentSchedule(
            policy=osago_policy,
            year_number=1,
            installment_number=1,
            due_date=osago_policy.start_date,
            insurance_sum=Decimal("400000"),
            amount=Decimal("12000"),
        )
        payment._date_sequence_checked_by_formset = True
        with pytest.raises(ValidationError) as exc:
            payment.full_clean()
        assert "insurance_sum" in exc.value.message_dict

    def test_non_osago_requires_insurance_sum(self, policy_factory, kasko_type):
        policy = policy_factory(insurance_type=kasko_type)
        with pytest.raises(ValidationError) as exc:
            make_payment(policy, insurance_sum=None)
        assert "insurance_sum" in exc.value.message_dict

    def test_non_osago_kv_is_not_capped(self, policy_factory, kasko_type):
        policy = policy_factory(insurance_type=kasko_type)
        make_payment(
            policy,
            insurance_sum=Decimal("1000000"),
            amount=Decimal("10000"),
            kv_rub=Decimal("3000"),
        )

    def test_rates_by_year_skips_osago(self, osago_policy):
        make_payment(osago_policy)
        assert osago_policy.get_rates_by_year() == []

    def test_kv_from_capped_rate_is_auto_calculated(self, osago_policy, osago_type):
        rate = CommissionRate.objects.create(
            insurer=osago_policy.insurer,
            insurance_type=osago_type,
            kv_percent=Decimal("10"),
        )
        payment = make_payment(osago_policy, commission_rate=rate, kv_rub=Decimal("0"))
        payment.refresh_from_db()
        assert payment.kv_rub == Decimal("1200.00")


class TestCommissionRateClean:
    def test_osago_rate_above_cap_is_rejected(self, insurer_factory, osago_type):
        rate = CommissionRate(
            insurer=insurer_factory(),
            insurance_type=osago_type,
            kv_percent=Decimal("10.5"),
        )
        with pytest.raises(ValidationError) as exc:
            rate.full_clean()
        assert "kv_percent" in exc.value.message_dict

    def test_osago_rate_at_cap_is_valid(self, insurer_factory, osago_type):
        CommissionRate(
            insurer=insurer_factory(),
            insurance_type=osago_type,
            kv_percent=Decimal("10"),
        ).full_clean()

    def test_non_osago_rate_is_not_capped(self, insurer_factory, kasko_type):
        CommissionRate(
            insurer=insurer_factory(),
            insurance_type=kasko_type,
            kv_percent=Decimal("25"),
        ).full_clean()
