"""
Unit tests for rates by year calculation.

Tests verify that get_rates_by_year method correctly calculates
insurance rates for each year based on payment schedule.
"""
import pytest
from decimal import Decimal


@pytest.mark.django_db
class TestRatesByYear:
    """Tests for Policy.get_rates_by_year method."""

    def test_rates_by_year_single_year(self, policy_factory, payment_schedule_factory):
        """
        Test rate calculation for a single year with multiple payments.
        """
        from datetime import date, timedelta

        # Create policy
        policy = policy_factory(policy_number="TEST-RATE-001")

        # Create payments for year 1
        # Insurance sum: 1,000,000
        # Payment 1: 50,000 (5%)
        # Payment 2: 30,000 (3%)
        # Total: 80,000 (8%)
        base_date = date.today()
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=base_date,
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("50000.00"),
        )
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            due_date=base_date + timedelta(days=30),
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("30000.00"),
        )

        # Calculate rates
        rates = policy.get_rates_by_year()

        # Verify
        assert len(rates) == 1
        assert rates[0]["year_number"] == 1
        assert rates[0]["total_premium"] == Decimal("80000.00")
        assert rates[0]["insurance_sum"] == Decimal("1000000.00")
        assert rates[0]["rate"] == Decimal("8.00")

    def test_rates_by_year_multiple_years(
        self, policy_factory, payment_schedule_factory
    ):
        """
        Test rate calculation for multiple years.
        """
        from datetime import date, timedelta

        # Create policy
        policy = policy_factory(policy_number="TEST-RATE-002")

        base_date = date.today()

        # Year 1: Insurance sum 1,000,000, Premium 80,000 (8%)
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=base_date,
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("50000.00"),
        )
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            due_date=base_date + timedelta(days=30),
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("30000.00"),
        )

        # Year 2: Insurance sum 900,000, Premium 63,000 (7%)
        payment_schedule_factory(
            policy=policy,
            year_number=2,
            installment_number=1,
            due_date=base_date + timedelta(days=365),
            insurance_sum=Decimal("900000.00"),
            amount=Decimal("40000.00"),
        )
        payment_schedule_factory(
            policy=policy,
            year_number=2,
            installment_number=2,
            due_date=base_date + timedelta(days=395),
            insurance_sum=Decimal("900000.00"),
            amount=Decimal("23000.00"),
        )

        # Calculate rates
        rates = policy.get_rates_by_year()

        # Verify
        assert len(rates) == 2

        # Year 1
        assert rates[0]["year_number"] == 1
        assert rates[0]["total_premium"] == Decimal("80000.00")
        assert rates[0]["insurance_sum"] == Decimal("1000000.00")
        assert rates[0]["rate"] == Decimal("8.00")

        # Year 2
        assert rates[1]["year_number"] == 2
        assert rates[1]["total_premium"] == Decimal("63000.00")
        assert rates[1]["insurance_sum"] == Decimal("900000.00")
        assert rates[1]["rate"] == Decimal("7.00")

    def test_rates_by_year_different_insurance_sum_within_year(
        self, policy_factory, payment_schedule_factory
    ):
        """
        Test that insurance sum is taken from the first payment when it differs within a year.
        """
        from datetime import date, timedelta

        # Create policy
        policy = policy_factory(policy_number="TEST-RATE-003")

        base_date = date.today()

        # Year 1: Insurance sum changes during the year
        # First payment: 1,000,000
        # Second payment: 950,000 (should be ignored for rate calculation)
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=base_date,
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("50000.00"),
        )
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            due_date=base_date + timedelta(days=30),
            insurance_sum=Decimal("950000.00"),  # Different insurance sum
            amount=Decimal("30000.00"),
        )

        # Calculate rates
        rates = policy.get_rates_by_year()

        # Verify - should use insurance_sum from first payment (1,000,000)
        assert len(rates) == 1
        assert rates[0]["year_number"] == 1
        assert rates[0]["total_premium"] == Decimal("80000.00")
        assert rates[0]["insurance_sum"] == Decimal("1000000.00")  # From first payment
        assert rates[0]["rate"] == Decimal("8.00")

    def test_rates_by_year_empty_schedule(self, policy_factory):
        """
        Test rate calculation for policy without payment schedule.
        """
        # Create policy without payments
        policy = policy_factory(policy_number="TEST-RATE-004")

        # Calculate rates
        rates = policy.get_rates_by_year()

        # Verify
        assert len(rates) == 0

    def test_rates_by_year_minimal_insurance_sum(
        self, policy_factory, payment_schedule_factory
    ):
        """
        Test rate calculation with minimal insurance sum (edge case).
        """
        from datetime import date

        # Create policy
        policy = policy_factory(policy_number="TEST-RATE-005")

        # Create payment with minimal insurance sum (0.01 is the minimum allowed)
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=date.today(),
            insurance_sum=Decimal("0.01"),
            amount=Decimal("50000.00"),
        )

        # Calculate rates
        rates = policy.get_rates_by_year()

        # Verify - rate should be very high when insurance_sum is minimal
        assert len(rates) == 1
        assert rates[0]["year_number"] == 1
        assert rates[0]["total_premium"] == Decimal("50000.00")
        assert rates[0]["insurance_sum"] == Decimal("0.01")
        # Rate = (50000 / 0.01) * 100 = 500000000%
        assert rates[0]["rate"] == Decimal("500000000")

    def test_rates_by_year_missing_first_installment(
        self, policy_factory, payment_schedule_factory
    ):
        """
        Test that years without first installment (installment_number=1) are excluded.

        This handles cases where only later installments were entered into the database,
        which would result in incorrect rate calculations.
        """
        from datetime import date, timedelta

        # Create policy
        policy = policy_factory(policy_number="TEST-RATE-006")

        base_date = date.today()

        # Year 1: Has first installment - should be included
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=base_date,
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("50000.00"),
        )
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            due_date=base_date + timedelta(days=30),
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("30000.00"),
        )

        # Year 2: Missing first installment (starts from installment 2) - should be excluded
        payment_schedule_factory(
            policy=policy,
            year_number=2,
            installment_number=2,
            due_date=base_date + timedelta(days=365),
            insurance_sum=Decimal("900000.00"),
            amount=Decimal("40000.00"),
        )
        payment_schedule_factory(
            policy=policy,
            year_number=2,
            installment_number=3,
            due_date=base_date + timedelta(days=395),
            insurance_sum=Decimal("900000.00"),
            amount=Decimal("23000.00"),
        )

        # Year 3: Has first installment - should be included
        payment_schedule_factory(
            policy=policy,
            year_number=3,
            installment_number=1,
            due_date=base_date + timedelta(days=730),
            insurance_sum=Decimal("800000.00"),
            amount=Decimal("48000.00"),
        )

        # Calculate rates
        rates = policy.get_rates_by_year()

        # Verify - only years 1 and 3 should be included (year 2 is excluded)
        assert len(rates) == 2

        # Year 1
        assert rates[0]["year_number"] == 1
        assert rates[0]["total_premium"] == Decimal("80000.00")
        assert rates[0]["insurance_sum"] == Decimal("1000000.00")
        assert rates[0]["rate"] == Decimal("8.00")

        # Year 3 (year 2 is skipped)
        assert rates[1]["year_number"] == 3
        assert rates[1]["total_premium"] == Decimal("48000.00")
        assert rates[1]["insurance_sum"] == Decimal("800000.00")
        assert rates[1]["rate"] == Decimal("6.00")
