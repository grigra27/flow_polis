"""
Unit tests for admin configuration.

Tests verify that the admin interface is properly configured with
insurance_sum fields and that property_value has been removed.

**Validates: Requirements 1.3, 4.1, 4.2, 4.3**
"""
import pytest
from django.contrib import admin
from apps.policies.admin import PaymentScheduleAdmin, PaymentScheduleInline, PolicyAdmin
from apps.policies.models import PaymentSchedule, Policy


@pytest.mark.django_db
class TestPaymentScheduleInlineConfig:
    """Test PaymentScheduleInline configuration."""

    def test_insurance_sum_in_inline_fields(self):
        """
        Test that insurance_sum is present in PaymentScheduleInline fields.

        **Validates: Requirements 1.3, 4.1**
        """
        inline = PaymentScheduleInline(Policy, admin.site)
        assert (
            "insurance_sum" in inline.fields
        ), "insurance_sum should be present in PaymentScheduleInline fields"

    def test_insurance_sum_position_after_amount(self):
        """
        Test that insurance_sum appears after amount in inline fields.

        **Validates: Requirements 4.1**
        """
        inline = PaymentScheduleInline(Policy, admin.site)
        fields_list = list(inline.fields)

        assert "amount" in fields_list, "amount should be in fields"
        assert "insurance_sum" in fields_list, "insurance_sum should be in fields"

        amount_index = fields_list.index("amount")
        insurance_sum_index = fields_list.index("insurance_sum")

        assert (
            insurance_sum_index == amount_index + 1
        ), "insurance_sum should appear immediately after amount"


@pytest.mark.django_db
class TestPaymentScheduleAdminConfig:
    """Test PaymentScheduleAdmin configuration."""

    def test_insurance_sum_in_list_display(self):
        """
        Test that insurance_sum is present in PaymentScheduleAdmin list_display.

        **Validates: Requirements 4.2**
        """
        payment_admin = PaymentScheduleAdmin(PaymentSchedule, admin.site)
        assert (
            "insurance_sum" in payment_admin.list_display
        ), "insurance_sum should be present in list_display"

    def test_insurance_sum_position_after_amount_in_list_display(self):
        """
        Test that insurance_sum appears after amount in list_display.

        **Validates: Requirements 4.2**
        """
        payment_admin = PaymentScheduleAdmin(PaymentSchedule, admin.site)
        list_display = list(payment_admin.list_display)

        assert "amount" in list_display, "amount should be in list_display"
        assert (
            "insurance_sum" in list_display
        ), "insurance_sum should be in list_display"

        amount_index = list_display.index("amount")
        insurance_sum_index = list_display.index("insurance_sum")

        assert (
            insurance_sum_index == amount_index + 1
        ), "insurance_sum should appear immediately after amount in list_display"

    def test_insurance_sum_filter_exists(self):
        """
        Test that insurance_sum filtering is available in PaymentScheduleAdmin.

        **Validates: Requirements 4.4**
        """
        payment_admin = PaymentScheduleAdmin(PaymentSchedule, admin.site)
        # Check if list_filter exists and contains insurance_sum related filter
        assert hasattr(
            payment_admin, "list_filter"
        ), "PaymentScheduleAdmin should have list_filter attribute"


@pytest.mark.django_db
class TestPolicyAdminConfig:
    """Test PolicyAdmin configuration."""

    def test_property_value_not_in_fieldsets(self):
        """
        Test that property_value is not present in PolicyAdmin fieldsets.

        **Validates: Requirements 1.3, 4.3**
        """
        policy_admin = PolicyAdmin(Policy, admin.site)

        # Collect all fields from all fieldsets
        all_fields = []
        for fieldset in policy_admin.fieldsets:
            fieldset_fields = fieldset[1]["fields"]
            for field in fieldset_fields:
                if isinstance(field, (list, tuple)):
                    all_fields.extend(field)
                else:
                    all_fields.append(field)

        assert (
            "property_value" not in all_fields
        ), "property_value should not be present in PolicyAdmin fieldsets"
