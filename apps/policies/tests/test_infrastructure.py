"""
Test to verify the testing infrastructure is properly set up.
"""
import pytest
from decimal import Decimal
from apps.policies.models import Policy, PaymentSchedule


@pytest.mark.unit
def test_fixtures_work(sample_client, sample_insurer, sample_policy, sample_payment):
    """Verify that all fixtures are working correctly."""
    # Test client fixture
    assert sample_client.client_name == "Sample Client Ltd"
    assert sample_client.client_inn == "9876543210"

    # Test insurer fixture
    assert sample_insurer.insurer_name == "Sample Insurance Co"

    # Test policy fixture
    assert sample_policy.policy_number == "SAMPLE-001"
    assert sample_policy.client == sample_client
    assert sample_policy.insurer == sample_insurer

    # Test payment fixture
    assert sample_payment.policy == sample_policy
    assert sample_payment.amount == Decimal("5000.00")
    assert sample_payment.year_number == 1
    assert sample_payment.installment_number == 1


@pytest.mark.unit
def test_factory_fixtures(client_factory, policy_factory, payment_schedule_factory):
    """Verify that factory fixtures can create custom instances."""
    # Create custom client
    client = client_factory(client_name="Custom Client", client_inn="1111111111")
    assert client.client_name == "Custom Client"
    assert client.client_inn == "1111111111"

    # Create custom policy
    policy = policy_factory(policy_number="CUSTOM-001", client=client)
    assert policy.policy_number == "CUSTOM-001"
    assert policy.client == client

    # Create custom payment
    payment = payment_schedule_factory(
        policy=policy, amount=Decimal("15000.00"), year_number=2, installment_number=3
    )
    assert payment.policy == policy
    assert payment.amount == Decimal("15000.00")
    assert payment.year_number == 2
    assert payment.installment_number == 3


@pytest.mark.unit
def test_database_access(db, client_factory):
    """Verify that database access is working."""
    # Create a client
    client = client_factory(client_name="DB Test Client")

    # Verify it was saved to the database
    from apps.clients.models import Client

    saved_client = Client.objects.get(client_name="DB Test Client")
    assert saved_client.id == client.id
    assert saved_client.client_name == "DB Test Client"
