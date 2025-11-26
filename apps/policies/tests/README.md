# Policy Payment Enhancements Tests

This directory contains tests for the policy payment enhancements feature.

## Test Infrastructure

### Running Tests

Run all tests in this directory:
```bash
pytest apps/policies/tests/
```

Run a specific test file:
```bash
pytest apps/policies/tests/test_infrastructure.py
```

Run tests with verbose output:
```bash
pytest apps/policies/tests/ -v
```

Run tests with a specific marker:
```bash
pytest apps/policies/tests/ -m unit
pytest apps/policies/tests/ -m property
```

### Test Fixtures

The `conftest.py` file provides reusable fixtures for creating test data:

#### Factory Fixtures
- `client_factory` - Create Client instances
- `insurer_factory` - Create Insurer instances
- `branch_factory` - Create Branch instances
- `insurance_type_factory` - Create InsuranceType instances
- `commission_rate_factory` - Create CommissionRate instances
- `policy_factory` - Create Policy instances
- `payment_schedule_factory` - Create PaymentSchedule instances

#### Pre-created Fixtures
- `sample_client` - A pre-created client
- `sample_insurer` - A pre-created insurer
- `sample_policy` - A pre-created policy with related objects
- `sample_payment` - A pre-created payment schedule
- `admin_user` - An admin user for testing admin interface

### Test Markers

Tests are categorized using pytest markers:
- `@pytest.mark.unit` - Unit tests for individual components
- `@pytest.mark.integration` - Integration tests for multiple components
- `@pytest.mark.property` - Property-based tests using Hypothesis
- `@pytest.mark.slow` - Tests that take a long time to run
- `@pytest.mark.migration` - Tests for database migrations
- `@pytest.mark.admin` - Tests for Django admin interface

### Property-Based Testing

Property-based tests use the Hypothesis library and are configured to run 100 examples per test (as per design document requirements).

Example:
```python
from hypothesis import given, strategies as st

@pytest.mark.property
@given(amount=st.decimals(min_value='0.01', max_value='1000000', places=2))
def test_payment_amount_property(payment_schedule_factory, amount):
    payment = payment_schedule_factory(amount=amount)
    assert payment.amount == amount
```

## Test Organization

- `test_infrastructure.py` - Tests to verify the testing infrastructure
- `test_models.py` - Unit tests for model functionality (to be created)
- `test_migrations.py` - Tests for database migrations (to be created)
- `test_admin.py` - Tests for admin interface (to be created)
- `test_properties.py` - Property-based tests (to be created)
