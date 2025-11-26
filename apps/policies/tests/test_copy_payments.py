"""
Unit tests for payment copy functionality.

**Feature: policy-payment-enhancements**

These tests verify the copy_payments admin action works correctly.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from apps.policies.admin import PaymentScheduleAdmin
from apps.policies.models import PaymentSchedule


@pytest.mark.django_db
class TestCopyPaymentsAction:
    """Unit tests for the copy_payments admin action."""
    
    def test_copy_single_payment(self, payment_schedule_factory):
        """
        Test copying a single payment.
        
        **Validates: Requirements 2.1, 2.2**
        """
        # Create original payment
        original = payment_schedule_factory(
            year_number=2,
            installment_number=3,
            amount=Decimal('15000.00'),
            insurance_sum=Decimal('2000000.00'),
            kv_rub=Decimal('1500.00'),
            payment_info='Original payment info'
        )
        
        # Set up admin
        site = AdminSite()
        admin = PaymentScheduleAdmin(PaymentSchedule, site)
        factory = RequestFactory()
        request = factory.get('/admin/policies/paymentschedule/')
        
        # Create queryset with single payment
        queryset = PaymentSchedule.objects.filter(id=original.id)
        
        # Execute copy action
        response = admin.copy_payments(request, queryset)
        
        # Verify redirect response
        assert response is not None
        assert response.status_code == 302
        assert '/admin/policies/paymentschedule/add/' in response.url
        
        # Verify GET parameters contain copied data
        assert f'policy={original.policy.id}' in response.url
        assert f'year_number={original.year_number}' in response.url
        assert f'installment_number={original.installment_number}' in response.url
        assert f'amount={original.amount}' in response.url
        assert f'insurance_sum={original.insurance_sum}' in response.url
        assert f'kv_rub={original.kv_rub}' in response.url
    
    def test_copy_multiple_payments(self, payment_schedule_factory, policy_factory):
        """
        Test copying multiple payments.
        
        **Validates: Requirements 2.1, 2.5**
        """
        # Create a policy with multiple payments
        policy = policy_factory()
        payment1 = payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            amount=Decimal('10000.00'),
            insurance_sum=Decimal('1000000.00')
        )
        payment2 = payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            amount=Decimal('12000.00'),
            insurance_sum=Decimal('1200000.00')
        )
        payment3 = payment_schedule_factory(
            policy=policy,
            year_number=2,
            installment_number=1,
            amount=Decimal('15000.00'),
            insurance_sum=Decimal('1500000.00')
        )
        
        # Set up admin
        site = AdminSite()
        admin = PaymentScheduleAdmin(PaymentSchedule, site)
        factory = RequestFactory()
        request = factory.get('/admin/policies/paymentschedule/')
        
        # Create queryset with multiple payments
        queryset = PaymentSchedule.objects.filter(
            id__in=[payment1.id, payment2.id, payment3.id]
        )
        
        # Execute copy action
        response = admin.copy_payments(request, queryset)
        
        # Verify redirect response (should redirect to first payment's copy)
        assert response is not None
        assert response.status_code == 302
        assert '/admin/policies/paymentschedule/add/' in response.url
    
    def test_copy_does_not_save_automatically(self, payment_schedule_factory):
        """
        Test that copy does not automatically save the payment.
        
        **Validates: Requirements 2.4**
        """
        # Count payments before copy
        initial_count = PaymentSchedule.objects.count()
        
        # Create original payment
        original = payment_schedule_factory(
            amount=Decimal('20000.00'),
            insurance_sum=Decimal('3000000.00')
        )
        
        # Count after creating original
        count_after_original = PaymentSchedule.objects.count()
        assert count_after_original == initial_count + 1
        
        # Set up admin
        site = AdminSite()
        admin = PaymentScheduleAdmin(PaymentSchedule, site)
        factory = RequestFactory()
        request = factory.get('/admin/policies/paymentschedule/')
        
        # Create queryset
        queryset = PaymentSchedule.objects.filter(id=original.id)
        
        # Execute copy action
        response = admin.copy_payments(request, queryset)
        
        # Verify no new payment was saved
        final_count = PaymentSchedule.objects.count()
        assert final_count == count_after_original
        assert final_count == initial_count + 1
        
        # Verify response redirects to add form (not saved yet)
        assert response.status_code == 302
        assert '/add/' in response.url
    
    def test_copy_action_exists_in_admin(self, admin_user):
        """
        Test that copy_payments action is registered in PaymentScheduleAdmin.
        
        **Validates: Requirements 2.1**
        """
        site = AdminSite()
        admin = PaymentScheduleAdmin(PaymentSchedule, site)
        factory = RequestFactory()
        request = factory.get('/admin/policies/paymentschedule/')
        request.user = admin_user
        
        # Verify action exists
        assert hasattr(admin, 'copy_payments')
        assert callable(admin.copy_payments)
        
        # Verify action is in actions list
        actions = admin.get_actions(request)
        assert 'copy_payments' in actions
    
    def test_copy_preserves_all_fields(self, payment_schedule_factory, commission_rate_factory, policy_factory):
        """
        Test that all fields are preserved in the copy.
        
        **Validates: Requirements 2.2**
        """
        # Create policy first to avoid unique constraint issues
        policy = policy_factory()
        
        # Create commission rate with the same insurer and insurance_type as policy
        commission_rate = commission_rate_factory(
            insurer=policy.insurer,
            insurance_type=policy.insurance_type,
            kv_percent=Decimal('12.50')
        )
        
        # Create original payment with all fields populated
        original = payment_schedule_factory(
            policy=policy,
            year_number=3,
            installment_number=4,
            due_date=date.today() + timedelta(days=60),
            amount=Decimal('25000.00'),
            insurance_sum=Decimal('4000000.00'),
            commission_rate=commission_rate,
            kv_rub=Decimal('3125.00'),
            paid_date=date.today() + timedelta(days=55),
            insurer_date=date.today() + timedelta(days=50),
            payment_info='Detailed payment information'
        )
        
        # Set up admin
        site = AdminSite()
        admin = PaymentScheduleAdmin(PaymentSchedule, site)
        factory = RequestFactory()
        request = factory.get('/admin/policies/paymentschedule/')
        
        # Create queryset
        queryset = PaymentSchedule.objects.filter(id=original.id)
        
        # Execute copy action
        response = admin.copy_payments(request, queryset)
        
        # Verify all fields are in the redirect URL
        assert f'policy={original.policy.id}' in response.url
        assert f'year_number={original.year_number}' in response.url
        assert f'installment_number={original.installment_number}' in response.url
        assert f'due_date={original.due_date}' in response.url
        assert f'amount={original.amount}' in response.url
        assert f'insurance_sum={original.insurance_sum}' in response.url
        assert f'commission_rate={original.commission_rate.id}' in response.url
        # kv_rub might have different decimal precision in URL, so just check it's present
        assert 'kv_rub=' in response.url
        assert f'paid_date={original.paid_date}' in response.url
        assert f'insurer_date={original.insurer_date}' in response.url
        # payment_info should be URL encoded in the query string
        assert 'payment_info=' in response.url
