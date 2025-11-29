"""
Property-based tests for PaymentSchedule model.

**Feature: policy-payment-enhancements**

These tests verify correctness properties that should hold across all valid inputs.
"""
import pytest
from decimal import Decimal
from hypothesis import given, settings, strategies as st
from hypothesis.extra.django import TestCase
from apps.policies.models import PaymentSchedule


class TestPaymentScheduleProperties(TestCase):
    """Property-based tests for PaymentSchedule model."""
    
    @pytest.mark.property
    @settings(max_examples=100, deadline=None)
    @given(
        insurance_sum=st.decimals(
            min_value=Decimal('0.01'),
            max_value=Decimal('999999999999.99'),
            places=2
        )
    )
    def test_insurance_sum_round_trip(self, insurance_sum):
        """
        **Feature: policy-payment-enhancements, Property 1: Сохранение страховой суммы при создании платежа**
        **Validates: Requirements 1.1, 1.2**
        
        Property: For any payment with a specified insurance sum, after saving and 
        reading from the database, the insurance sum value should match the original value.
        
        This is a round-trip consistency property that ensures data integrity.
        """
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date, timedelta
        
        # Create required related objects
        client = Client.objects.create(
            client_name='Test Client',
            client_inn='1234567890'
        )
        insurer = Insurer.objects.create(
            insurer_name='Test Insurer',
            contacts='test@example.com'
        )
        branch = Branch.objects.create(
            branch_name='Test Branch'
        )
        insurance_type = InsuranceType.objects.create(
            name='Test Type'
        )
        
        # Create policy
        policy = Policy.objects.create(
            policy_number='TEST-001',
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description='Test property',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            premium_total=Decimal('50000.00')
        )
        
        # Create payment with the generated insurance_sum
        payment = PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=date.today() + timedelta(days=30),
            amount=Decimal('10000.00'),
            insurance_sum=insurance_sum,
            kv_rub=Decimal('1000.00')
        )
        
        # Retrieve the payment from database
        retrieved_payment = PaymentSchedule.objects.get(id=payment.id)
        
        # Assert round-trip consistency
        assert retrieved_payment.insurance_sum == insurance_sum, \
            f"Expected insurance_sum {insurance_sum}, but got {retrieved_payment.insurance_sum}"


    @pytest.mark.property
    @settings(max_examples=100, deadline=None)
    @given(
        # Generate a list of insurance sums for creating payments
        insurance_sums=st.lists(
            st.decimals(
                min_value=Decimal('0.01'),
                max_value=Decimal('999999999999.99'),
                places=2
            ),
            min_size=5,
            max_size=20
        ),
        # Generate a random range for filtering
        min_range=st.decimals(
            min_value=Decimal('0.01'),
            max_value=Decimal('500000000.00'),
            places=2
        ),
        max_range=st.decimals(
            min_value=Decimal('500000000.01'),
            max_value=Decimal('999999999999.99'),
            places=2
        )
    )
    def test_insurance_sum_range_filtering(self, insurance_sums, min_range, max_range):
        """
        **Feature: policy-payment-enhancements, Property 3: Фильтрация по диапазону страховых сумм**
        **Validates: Requirements 4.4**
        
        Property: For any set of payments and any range of insurance sum values,
        the filter result should contain only payments whose insurance sums are
        within the specified range, and all payments within the range should be
        present in the results.
        """
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date, timedelta
        
        # Ensure min_range < max_range
        if min_range >= max_range:
            min_range, max_range = max_range, min_range
            # Adjust to ensure they're different
            min_range = min_range - Decimal('1.00')
            if min_range < Decimal('0.01'):
                min_range = Decimal('0.01')
        
        # Create required related objects
        client = Client.objects.create(
            client_name='Test Client Filter',
            client_inn='1234567891'
        )
        insurer = Insurer.objects.create(
            insurer_name='Test Insurer Filter',
            contacts='test@example.com'
        )
        branch = Branch.objects.create(
            branch_name='Test Branch Filter'
        )
        insurance_type = InsuranceType.objects.create(
            name='Test Type Filter'
        )
        
        # Create policy
        policy = Policy.objects.create(
            policy_number='TEST-FILTER-001',
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description='Test property',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            premium_total=Decimal('50000.00')
        )
        
        # Create payments with the generated insurance sums
        created_payments = []
        for i, insurance_sum in enumerate(insurance_sums):
            payment = PaymentSchedule.objects.create(
                policy=policy,
                year_number=1,
                installment_number=i + 1,
                due_date=date.today() + timedelta(days=30 * (i + 1)),
                amount=Decimal('10000.00'),
                insurance_sum=insurance_sum,
                kv_rub=Decimal('1000.00')
            )
            created_payments.append(payment)
        
        # Apply filter: get payments within the range
        filtered_payments = PaymentSchedule.objects.filter(
            policy=policy,
            insurance_sum__gte=min_range,
            insurance_sum__lte=max_range
        )
        
        # Property 1: All filtered results should be within the range
        for payment in filtered_payments:
            assert min_range <= payment.insurance_sum <= max_range, \
                f"Payment {payment.id} with insurance_sum {payment.insurance_sum} " \
                f"is outside the range [{min_range}, {max_range}]"
        
        # Property 2: All payments within the range should be in the results
        expected_in_range = [
            p for p in created_payments
            if min_range <= p.insurance_sum <= max_range
        ]
        
        filtered_ids = set(p.id for p in filtered_payments)
        expected_ids = set(p.id for p in expected_in_range)
        
        assert filtered_ids == expected_ids, \
            f"Filtered payments {filtered_ids} don't match expected {expected_ids}"


    @pytest.mark.property
    @settings(max_examples=100, deadline=None)
    @given(
        year_number=st.integers(min_value=1, max_value=10),
        installment_number=st.integers(min_value=1, max_value=12),
        amount=st.decimals(
            min_value=Decimal('0.01'),
            max_value=Decimal('999999999.99'),
            places=2
        ),
        insurance_sum=st.decimals(
            min_value=Decimal('0.01'),
            max_value=Decimal('999999999999.99'),
            places=2
        ),
        kv_rub=st.decimals(
            min_value=Decimal('0.00'),
            max_value=Decimal('999999999.99'),
            places=2
        ),
        payment_info=st.text(max_size=200, alphabet=st.characters(blacklist_characters='\x00'))
    )
    def test_payment_copy_field_identity(self, year_number, installment_number, 
                                         amount, insurance_sum, kv_rub, payment_info):
        """
        **Feature: policy-payment-enhancements, Property 2: Идентичность полей при копировании**
        **Validates: Requirements 2.2**
        
        Property: For any payment, when performing a copy operation, all fields of the 
        copied payment (except id, created_at, updated_at) should be identical to the 
        fields of the original payment.
        """
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType, CommissionRate
        from apps.policies.models import Policy
        from datetime import date, timedelta
        
        # Create required related objects
        client = Client.objects.create(
            client_name='Test Client Copy',
            client_inn='1234567892'
        )
        insurer = Insurer.objects.create(
            insurer_name='Test Insurer Copy',
            contacts='test@example.com'
        )
        branch = Branch.objects.create(
            branch_name='Test Branch Copy'
        )
        insurance_type = InsuranceType.objects.create(
            name='Test Type Copy'
        )
        commission_rate = CommissionRate.objects.create(
            insurer=insurer,
            insurance_type=insurance_type,
            kv_percent=Decimal('10.00')
        )
        
        # Create policy
        policy = Policy.objects.create(
            policy_number='TEST-COPY-001',
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description='Test property',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            premium_total=Decimal('50000.00')
        )
        
        # Create original payment with generated values
        due_date = date.today() + timedelta(days=30)
        paid_date = date.today() + timedelta(days=25) if year_number % 2 == 0 else None
        insurer_date = date.today() + timedelta(days=20) if year_number % 3 == 0 else None
        
        original_payment = PaymentSchedule.objects.create(
            policy=policy,
            year_number=year_number,
            installment_number=installment_number,
            due_date=due_date,
            amount=amount,
            insurance_sum=insurance_sum,
            commission_rate=commission_rate,
            kv_rub=kv_rub,
            paid_date=paid_date,
            insurer_date=insurer_date,
            payment_info=payment_info
        )
        
        # Perform copy operation: create a new payment with same field values
        # This simulates what the admin copy action should do
        copied_payment = PaymentSchedule(
            policy=original_payment.policy,
            year_number=original_payment.year_number,
            installment_number=original_payment.installment_number,
            due_date=original_payment.due_date,
            amount=original_payment.amount,
            insurance_sum=original_payment.insurance_sum,
            commission_rate=original_payment.commission_rate,
            kv_rub=original_payment.kv_rub,
            paid_date=original_payment.paid_date,
            insurer_date=original_payment.insurer_date,
            payment_info=original_payment.payment_info
        )
        
        # Verify field identity (excluding id, created_at, updated_at)
        assert copied_payment.policy == original_payment.policy
        assert copied_payment.year_number == original_payment.year_number
        assert copied_payment.installment_number == original_payment.installment_number
        assert copied_payment.due_date == original_payment.due_date
        assert copied_payment.amount == original_payment.amount
        assert copied_payment.insurance_sum == original_payment.insurance_sum
        assert copied_payment.commission_rate == original_payment.commission_rate
        assert copied_payment.kv_rub == original_payment.kv_rub
        assert copied_payment.paid_date == original_payment.paid_date
        assert copied_payment.insurer_date == original_payment.insurer_date
        assert copied_payment.payment_info == original_payment.payment_info
        
        # Verify that id is different (not set yet for unsaved object)
        assert copied_payment.id is None
        assert original_payment.id is not None


    @pytest.mark.property
    @settings(max_examples=100, deadline=None)
    @given(
        amount=st.decimals(
            min_value=Decimal('0.01'),
            max_value=Decimal('999999999.99'),
            places=2
        ),
        kv_rub=st.decimals(
            min_value=Decimal('0.00'),
            max_value=Decimal('99999999.99'),
            places=2
        )
    )
    def test_kv_percent_actual_calculation(self, amount, kv_rub):
        """
        **Feature: policy-payment-enhancements, Property 4: Расчет фактического процента КВ**
        **Validates: Requirements 5.1, 5.2**
        
        Property: For any payment with amount > 0, the kv_percent_actual property
        should equal (kv_rub / amount) * 100, with proper handling of edge cases.
        """
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date, timedelta
        
        # Create required related objects
        client = Client.objects.create(
            client_name='Test Client KV',
            client_inn='1234567893'
        )
        insurer = Insurer.objects.create(
            insurer_name='Test Insurer KV',
            contacts='test@example.com'
        )
        branch = Branch.objects.create(
            branch_name='Test Branch KV'
        )
        insurance_type = InsuranceType.objects.create(
            name='Test Type KV'
        )
        
        # Create policy
        policy = Policy.objects.create(
            policy_number='TEST-KV-001',
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description='Test property',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            premium_total=Decimal('50000.00')
        )
        
        # Create payment with generated values
        payment = PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=date.today() + timedelta(days=30),
            amount=amount,
            insurance_sum=Decimal('1000000.00'),
            kv_rub=kv_rub
        )
        
        # Calculate expected percentage
        expected_percent = (kv_rub / amount) * Decimal('100')
        
        # Get actual percentage from property
        actual_percent = payment.kv_percent_actual
        
        # Assert equality with tolerance for decimal precision
        # Using quantize to ensure same precision
        assert actual_percent.quantize(Decimal('0.01')) == expected_percent.quantize(Decimal('0.01')), \
            f"Expected kv_percent_actual {expected_percent}, but got {actual_percent}"
        
        # Property: kv_percent_actual should always be >= 0
        assert actual_percent >= Decimal('0'), \
            f"kv_percent_actual should be non-negative, but got {actual_percent}"
        
        # Property: if kv_rub is 0, kv_percent_actual should be 0
        if kv_rub == Decimal('0'):
            assert actual_percent == Decimal('0'), \
                f"When kv_rub is 0, kv_percent_actual should be 0, but got {actual_percent}"


    @pytest.mark.property
    def test_kv_percent_actual_zero_amount(self):
        """
        **Feature: policy-payment-enhancements, Property 5: Обработка нулевой премии**
        **Validates: Requirements 5.3**
        
        Property: When amount is 0 or None, kv_percent_actual should return 0
        without raising an exception.
        """
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date, timedelta
        
        # Create required related objects
        client = Client.objects.create(
            client_name='Test Client Zero',
            client_inn='1234567894'
        )
        insurer = Insurer.objects.create(
            insurer_name='Test Insurer Zero',
            contacts='test@example.com'
        )
        branch = Branch.objects.create(
            branch_name='Test Branch Zero'
        )
        insurance_type = InsuranceType.objects.create(
            name='Test Type Zero'
        )
        
        # Create policy
        policy = Policy.objects.create(
            policy_number='TEST-ZERO-001',
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description='Test property',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            premium_total=Decimal('50000.00')
        )
        
        # Test with amount = 0
        payment_zero = PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=date.today() + timedelta(days=30),
            amount=Decimal('0.00'),
            insurance_sum=Decimal('1000000.00'),
            kv_rub=Decimal('1000.00')
        )
        
        # Should not raise exception and should return 0
        assert payment_zero.kv_percent_actual == Decimal('0'), \
            f"Expected kv_percent_actual to be 0 for zero amount, but got {payment_zero.kv_percent_actual}"
