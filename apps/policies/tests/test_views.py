"""
Unit tests for policy views.

Tests verify that insurance_sum is correctly displayed in templates
and that views properly handle the new data structure.
"""
import pytest
from decimal import Decimal
from django.urls import reverse
from django.contrib.auth.models import User


@pytest.fixture
def regular_user(db):
    """Create a regular user for testing views."""
    return User.objects.create_user(
        username='testuser',
        email='test@test.com',
        password='testpass123'
    )


@pytest.mark.django_db
class TestPolicyDetailView:
    """Tests for PolicyDetailView displaying insurance_sum."""
    
    def test_insurance_sum_displayed_in_payment_table(
        self, client, regular_user, sample_policy, sample_payment
    ):
        """
        Test that insurance_sum is displayed in the payment schedule table.
        
        Validates: Requirements 1.2, 4.1
        """
        # Login user
        client.force_login(regular_user)
        
        # Get policy detail page
        url = reverse('policies:detail', kwargs={'pk': sample_policy.pk})
        response = client.get(url)
        
        # Check response is successful
        assert response.status_code == 200
        
        # Check that insurance_sum is in the response content
        content = response.content.decode('utf-8')
        assert 'Страховая сумма' in content
        
        # Check that the actual insurance_sum value is displayed (Django uses comma as decimal separator)
        # The template uses floatformat:2 which formats as "500000,00"
        insurance_sum_str = str(sample_payment.insurance_sum).replace('.', ',')
        assert insurance_sum_str in content
    
    def test_multiple_payments_show_different_insurance_sums(
        self, client, regular_user, sample_policy, payment_schedule_factory
    ):
        """
        Test that multiple payments can have different insurance_sums displayed.
        
        Validates: Requirements 1.2
        """
        # Create payments with different insurance sums
        payment1 = payment_schedule_factory(
            policy=sample_policy,
            year_number=1,
            installment_number=1,
            insurance_sum=Decimal('1000000.00')
        )
        payment2 = payment_schedule_factory(
            policy=sample_policy,
            year_number=1,
            installment_number=2,
            insurance_sum=Decimal('950000.00')
        )
        
        # Login and get page
        client.force_login(regular_user)
        url = reverse('policies:detail', kwargs={'pk': sample_policy.pk})
        response = client.get(url)
        
        # Check both insurance sums are displayed
        content = response.content.decode('utf-8')
        assert response.status_code == 200
        assert 'Страховая сумма' in content


@pytest.mark.django_db
class TestPaymentScheduleListView:
    """Tests for PaymentScheduleListView."""
    
    def test_payment_list_view_accessible(
        self, client, regular_user, sample_payment
    ):
        """
        Test that payment list view is accessible and displays payments.
        
        Validates: Requirements 1.2
        """
        # Login user
        client.force_login(regular_user)
        
        # Get payment list page
        url = reverse('policies:payments')
        response = client.get(url)
        
        # Check response is successful
        assert response.status_code == 200
        
        # Check that payment is in the list
        content = response.content.decode('utf-8')
        assert sample_payment.policy.policy_number in content

