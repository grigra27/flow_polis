"""
Unit tests for policy copy functionality.

These tests verify the copy_policy admin action works correctly.
The action creates a complete copy of the policy including payment schedule and info tags.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from apps.policies.admin import PolicyAdmin
from apps.policies.models import Policy, PaymentSchedule, PolicyInfo


@pytest.mark.django_db
class TestCopyPolicyAction:
    """Unit tests for the copy_policy admin action."""

    def test_copy_single_policy(self, policy_factory):
        """
        Test copying a single policy creates a new policy with copied data.
        """
        # Create leasing manager
        from apps.insurers.models import LeasingManager

        leasing_manager = LeasingManager.objects.create(
            name="Test Manager",
            full_name="Test Manager Full Name",
            phone="+7 (123) 456-78-90",
            email="test@example.com",
        )

        # Create original policy
        original = policy_factory(
            policy_number="TEST-2024-001",
            dfa_number="DFA-2024-001",
            property_description="Test property description",
            franchise=Decimal("5000.00"),
            leasing_manager=leasing_manager,
            info3="Info 3 content",
            info4="Info 4 content",
            policy_active=True,
            dfa_active=True,
            policy_uploaded=False,
        )

        initial_count = Policy.objects.count()

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")

        # Add session and messages to request
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset with single policy
        queryset = Policy.objects.filter(id=original.id)

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Verify a new policy was created
        assert Policy.objects.count() == initial_count + 1

        # Get the new policy
        new_policy = Policy.objects.exclude(id=original.id).first()
        assert new_policy is not None

        # Verify redirect to edit page
        assert response is not None
        assert response.status_code == 302
        assert f"/admin/policies/policy/{new_policy.id}/change/" in response.url

        # Verify copied fields
        assert "TEST-2024-001-COPY" in new_policy.policy_number
        assert "DFA-2024-001-COPY" in new_policy.dfa_number
        assert new_policy.client == original.client
        assert new_policy.insurer == original.insurer
        assert new_policy.property_description == original.property_description
        assert new_policy.franchise == original.franchise
        assert new_policy.leasing_manager == original.leasing_manager
        assert new_policy.info3 == original.info3
        assert new_policy.info4 == original.info4
        assert new_policy.policy_active == original.policy_active
        assert new_policy.dfa_active == original.dfa_active
        assert new_policy.policy_uploaded == original.policy_uploaded

    def test_copy_policy_with_policyholder(self, policy_factory, client_factory):
        """
        Test copying a policy with policyholder field populated.
        """
        # Create policyholder
        policyholder = client_factory()

        # Create original policy with policyholder
        original = policy_factory(
            policy_number="TEST-2024-002", policyholder=policyholder
        )

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset
        queryset = Policy.objects.filter(id=original.id)

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Get the new policy
        new_policy = Policy.objects.exclude(id=original.id).first()

        # Verify policyholder was copied
        assert new_policy.policyholder == original.policyholder

    def test_copy_multiple_policies(
        self,
        policy_factory,
        client_factory,
        insurer_factory,
        insurance_type_factory,
        branch_factory,
    ):
        """
        Test copying multiple policies (should copy first one by ordering).
        """
        # Create shared dependencies to avoid unique constraint issues
        client = client_factory()
        insurer = insurer_factory()
        insurance_type = insurance_type_factory()
        branch = branch_factory()

        initial_count = Policy.objects.count()

        # Create multiple policies with shared dependencies
        policy1 = policy_factory(
            policy_number="TEST-2024-003",
            client=client,
            insurer=insurer,
            insurance_type=insurance_type,
            branch=branch,
        )
        policy2 = policy_factory(
            policy_number="TEST-2024-004",
            client=client,
            insurer=insurer,
            insurance_type=insurance_type,
            branch=branch,
        )
        policy3 = policy_factory(
            policy_number="TEST-2024-005",
            client=client,
            insurer=insurer,
            insurance_type=insurance_type,
            branch=branch,
        )

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset with multiple policies
        queryset = Policy.objects.filter(id__in=[policy1.id, policy2.id, policy3.id])

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Verify only one new policy was created
        assert Policy.objects.count() == initial_count + 4  # 3 original + 1 copy

        # Verify redirect response
        assert response is not None
        assert response.status_code == 302
        assert "/admin/policies/policy/" in response.url
        assert "/change/" in response.url

    def test_copy_creates_new_policy(self, policy_factory):
        """
        Test that copy creates a new policy immediately.
        """
        # Count policies before copy
        initial_count = Policy.objects.count()

        # Create original policy
        original = policy_factory(policy_number="TEST-2024-006")

        # Count after creating original
        count_after_original = Policy.objects.count()
        assert count_after_original == initial_count + 1

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset
        queryset = Policy.objects.filter(id=original.id)

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Verify new policy was created
        final_count = Policy.objects.count()
        assert final_count == count_after_original + 1
        assert final_count == initial_count + 2

        # Verify response redirects to change form
        assert response.status_code == 302
        assert "/change/" in response.url

    def test_copy_action_exists_in_admin(self, admin_user):
        """
        Test that copy_policy action is registered in PolicyAdmin.
        """
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.user = admin_user

        # Verify action exists
        assert hasattr(admin, "copy_policy")
        assert callable(admin.copy_policy)

        # Verify action is in actions list
        actions = admin.get_actions(request)
        assert "copy_policy" in actions

    def test_copy_preserves_all_fields(self, policy_factory, client_factory):
        """
        Test that all fields are preserved in the copy.
        """
        # Create policyholder
        policyholder = client_factory()

        # Create original policy with all fields populated
        original = policy_factory(
            policy_number="TEST-2024-007",
            dfa_number="DFA-2024-007",
            policyholder=policyholder,
            property_description="Detailed property description",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            franchise=Decimal("10000.00"),
            leasing_manager="John Doe",
            info3="Important info 3",
            info4="Important info 4",
            policy_active=True,
            dfa_active=False,
            policy_uploaded=True,
        )

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset
        queryset = Policy.objects.filter(id=original.id)

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Get the new policy
        new_policy = Policy.objects.exclude(id=original.id).first()

        # Verify all fields are preserved
        assert "TEST-2024-007-COPY" in new_policy.policy_number
        assert "DFA-2024-007-COPY" in new_policy.dfa_number
        assert new_policy.client == original.client
        assert new_policy.policyholder == original.policyholder
        assert new_policy.insurer == original.insurer
        assert new_policy.insurance_type == original.insurance_type
        assert new_policy.branch == original.branch
        assert new_policy.start_date == original.start_date
        assert new_policy.end_date == original.end_date
        assert new_policy.franchise == original.franchise
        assert new_policy.leasing_manager == original.leasing_manager
        assert new_policy.property_description == original.property_description
        assert new_policy.info3 == original.info3
        assert new_policy.info4 == original.info4
        assert new_policy.policy_active == original.policy_active
        assert new_policy.dfa_active == original.dfa_active
        assert new_policy.policy_uploaded == original.policy_uploaded

    def test_copy_with_payment_schedule(self, policy_factory, payment_schedule_factory):
        """
        Test that payment schedule is copied along with the policy.
        """
        # Create original policy
        original = policy_factory(policy_number="TEST-2024-008")

        # Create payment schedule for original policy
        payment1 = payment_schedule_factory(
            policy=original,
            year_number=1,
            installment_number=1,
            amount=Decimal("10000.00"),
            insurance_sum=Decimal("1000000.00"),
            kv_rub=Decimal("1000.00"),
        )
        payment2 = payment_schedule_factory(
            policy=original,
            year_number=1,
            installment_number=2,
            amount=Decimal("12000.00"),
            insurance_sum=Decimal("1200000.00"),
            kv_rub=Decimal("1200.00"),
        )

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset
        queryset = Policy.objects.filter(id=original.id)

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Get the new policy
        new_policy = Policy.objects.exclude(id=original.id).first()

        # Verify payment schedule was copied
        new_payments = new_policy.payment_schedule.all()
        assert new_payments.count() == 2

        # Verify payment details
        new_payment1 = new_payments.filter(installment_number=1).first()
        assert new_payment1.year_number == payment1.year_number
        assert new_payment1.amount == payment1.amount
        assert new_payment1.insurance_sum == payment1.insurance_sum
        assert new_payment1.kv_rub == payment1.kv_rub

        new_payment2 = new_payments.filter(installment_number=2).first()
        assert new_payment2.year_number == payment2.year_number
        assert new_payment2.amount == payment2.amount

    def test_copy_with_info_tags(self, policy_factory):
        """
        Test that info tags are copied along with the policy.
        """
        from apps.insurers.models import InfoTag

        # Create original policy
        original = policy_factory(policy_number="TEST-2024-009")

        # Create info tags for original policy
        tag1 = InfoTag.objects.create(name="Test Tag 1")
        tag2 = InfoTag.objects.create(name="Test Tag 2")

        PolicyInfo.objects.create(policy=original, tag=tag1, info_field=1)
        PolicyInfo.objects.create(policy=original, tag=tag2, info_field=2)

        # Set up admin
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        factory = RequestFactory()
        request = factory.get("/admin/policies/policy/")
        request.session = {}
        request._messages = FallbackStorage(request)

        # Create queryset
        queryset = Policy.objects.filter(id=original.id)

        # Execute copy action
        response = admin.copy_policy(request, queryset)

        # Get the new policy
        new_policy = Policy.objects.exclude(id=original.id).first()

        # Verify info tags were copied
        new_info_tags = new_policy.info_tags.all()
        assert new_info_tags.count() == 2

        # Verify tag details
        assert new_info_tags.filter(tag=tag1, info_field=1).exists()
        assert new_info_tags.filter(tag=tag2, info_field=2).exists()
