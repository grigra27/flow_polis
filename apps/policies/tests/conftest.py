"""
Pytest fixtures for policy payment enhancements tests.

This module provides reusable test fixtures for creating test data
for policies, payments, clients, insurers, and related models.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta


@pytest.fixture
def client_factory(db):
    """
    Factory fixture for creating Client instances.
    
    Usage:
        client = client_factory(client_name="Test Company")
    """
    from apps.clients.models import Client
    
    def create_client(**kwargs):
        defaults = {
            'client_name': 'Test Client Company',
            'client_inn': '1234567890',
            'notes': 'Test client notes'
        }
        defaults.update(kwargs)
        return Client.objects.create(**defaults)
    
    return create_client


@pytest.fixture
def insurer_factory(db):
    """
    Factory fixture for creating Insurer instances.
    
    Usage:
        insurer = insurer_factory(insurer_name="Test Insurance Co")
    """
    from apps.insurers.models import Insurer
    
    def create_insurer(**kwargs):
        defaults = {
            'insurer_name': 'Test Insurance Company',
            'contacts': 'https://example.com/contacts',
            'notes': 'Test insurer notes'
        }
        defaults.update(kwargs)
        return Insurer.objects.create(**defaults)
    
    return create_insurer


@pytest.fixture
def branch_factory(db):
    """
    Factory fixture for creating Branch instances.
    
    Usage:
        branch = branch_factory(branch_name="Moscow Branch")
    """
    from apps.insurers.models import Branch
    
    def create_branch(**kwargs):
        defaults = {
            'branch_name': 'Test Branch'
        }
        defaults.update(kwargs)
        return Branch.objects.create(**defaults)
    
    return create_branch


@pytest.fixture
def insurance_type_factory(db):
    """
    Factory fixture for creating InsuranceType instances.
    
    Usage:
        ins_type = insurance_type_factory(name="КАСКО")
    """
    from apps.insurers.models import InsuranceType
    
    def create_insurance_type(**kwargs):
        defaults = {
            'name': 'Test Insurance Type'
        }
        defaults.update(kwargs)
        return InsuranceType.objects.create(**defaults)
    
    return create_insurance_type


@pytest.fixture
def commission_rate_factory(db, insurer_factory, insurance_type_factory):
    """
    Factory fixture for creating CommissionRate instances.
    
    Usage:
        rate = commission_rate_factory(kv_percent=Decimal('15.00'))
    """
    from apps.insurers.models import CommissionRate
    
    def create_commission_rate(**kwargs):
        if 'insurer' not in kwargs:
            kwargs['insurer'] = insurer_factory()
        if 'insurance_type' not in kwargs:
            kwargs['insurance_type'] = insurance_type_factory()
        
        defaults = {
            'kv_percent': Decimal('10.00')
        }
        defaults.update(kwargs)
        return CommissionRate.objects.create(**defaults)
    
    return create_commission_rate


@pytest.fixture
def policy_factory(db, client_factory, insurer_factory, branch_factory, insurance_type_factory):
    """
    Factory fixture for creating Policy instances.
    
    Usage:
        policy = policy_factory(policy_number="POL-001")
    """
    from apps.policies.models import Policy
    
    def create_policy(**kwargs):
        if 'client' not in kwargs:
            kwargs['client'] = client_factory()
        if 'insurer' not in kwargs:
            kwargs['insurer'] = insurer_factory()
        if 'branch' not in kwargs:
            kwargs['branch'] = branch_factory()
        if 'insurance_type' not in kwargs:
            kwargs['insurance_type'] = insurance_type_factory()
        
        defaults = {
            'policy_number': 'TEST-POL-001',
            'dfa_number': 'TEST-DFA-001',
            'property_description': 'Test property description',
            'start_date': date.today(),
            'end_date': date.today() + timedelta(days=365),
            'premium_total': Decimal('50000.00'),
            'leasing_manager': 'Test Manager',
            'franchise': Decimal('5000.00'),
            'info3': 'Test info 3',
            'info4': 'Test info 4',
            'policy_active': True,
            'dfa_active': True
        }
        defaults.update(kwargs)
        return Policy.objects.create(**defaults)
    
    return create_policy


@pytest.fixture
def payment_schedule_factory(db, policy_factory, commission_rate_factory):
    """
    Factory fixture for creating PaymentSchedule instances.
    
    Usage:
        payment = payment_schedule_factory(amount=Decimal('10000.00'))
    """
    from apps.policies.models import PaymentSchedule
    
    def create_payment_schedule(**kwargs):
        if 'policy' not in kwargs:
            kwargs['policy'] = policy_factory()
        
        defaults = {
            'year_number': 1,
            'installment_number': 1,
            'due_date': date.today() + timedelta(days=30),
            'amount': Decimal('10000.00'),
            'insurance_sum': Decimal('1000000.00'),
            'kv_rub': Decimal('1000.00'),
            'payment_info': 'Test payment info'
        }
        defaults.update(kwargs)
        return PaymentSchedule.objects.create(**defaults)
    
    return create_payment_schedule


@pytest.fixture
def sample_client(client_factory):
    """
    Fixture providing a pre-created sample client.
    
    Usage:
        def test_something(sample_client):
            assert sample_client.client_name == "Sample Client Ltd"
    """
    return client_factory(
        client_name="Sample Client Ltd",
        client_inn="9876543210"
    )


@pytest.fixture
def sample_insurer(insurer_factory):
    """
    Fixture providing a pre-created sample insurer.
    
    Usage:
        def test_something(sample_insurer):
            assert sample_insurer.insurer_name == "Sample Insurance Co"
    """
    return insurer_factory(
        insurer_name="Sample Insurance Co"
    )


@pytest.fixture
def sample_policy(policy_factory, sample_client, sample_insurer):
    """
    Fixture providing a pre-created sample policy with related objects.
    
    Usage:
        def test_something(sample_policy):
            assert sample_policy.policy_number == "SAMPLE-001"
    """
    return policy_factory(
        policy_number="SAMPLE-001",
        client=sample_client,
        insurer=sample_insurer
    )


@pytest.fixture
def sample_payment(payment_schedule_factory, sample_policy):
    """
    Fixture providing a pre-created sample payment schedule.
    
    Usage:
        def test_something(sample_payment):
            assert sample_payment.amount == Decimal('5000.00')
    """
    return payment_schedule_factory(
        policy=sample_policy,
        amount=Decimal('5000.00'),
        insurance_sum=Decimal('500000.00'),
        year_number=1,
        installment_number=1
    )


@pytest.fixture
def admin_user(db):
    """
    Fixture providing an admin user for testing admin interface.
    
    Usage:
        def test_admin_view(admin_user, client):
            client.force_login(admin_user)
            response = client.get('/admin/policies/policy/')
            assert response.status_code == 200
    """
    from django.contrib.auth.models import User
    return User.objects.create_superuser(
        username='admin',
        email='admin@test.com',
        password='admin123'
    )
