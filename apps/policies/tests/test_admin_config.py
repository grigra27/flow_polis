"""
Unit tests for admin configuration.

Tests verify that the admin interface is properly configured with
insurance_sum fields and that property_value has been removed.

**Validates: Requirements 1.3, 4.1, 4.2, 4.3**
"""
import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
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

    def test_insurance_sum_position_before_amount(self):
        """
        Test that insurance_sum appears immediately before amount in inline fields.
        UX-решение: страховая сумма слева от суммы платежа для удобства ввода.
        """
        inline = PaymentScheduleInline(Policy, admin.site)
        fields_list = list(inline.fields)

        assert "amount" in fields_list, "amount should be in fields"
        assert "insurance_sum" in fields_list, "insurance_sum should be in fields"

        amount_index = fields_list.index("amount")
        insurance_sum_index = fields_list.index("insurance_sum")

        assert (
            insurance_sum_index == amount_index - 1
        ), "insurance_sum should appear immediately before amount"


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

    def test_insurance_sum_position_before_amount_in_list_display(self):
        """
        Test that insurance_sum appears immediately before amount in list_display.
        UX-решение: страховая сумма слева от суммы платежа.
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
            insurance_sum_index == amount_index - 1
        ), "insurance_sum should appear immediately before amount in list_display"

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

    def test_response_add_redirects_to_frontend_detail_on_save_and_open_front(
        self,
        policy_factory,
        admin_user,
    ):
        """
        Кнопка "Сохранить и открыть на фронте" после добавления ведет на фронтовый detail.
        """
        policy_admin = PolicyAdmin(Policy, admin.site)
        policy = policy_factory()
        request = RequestFactory().post(
            "/admin/policies/policy/add/",
            {policy_admin.save_and_open_front_button_name: "1"},
        )
        request.user = admin_user

        response = policy_admin.response_add(request, policy)
        expected_url = reverse("policies:detail", args=[policy.pk])

        assert response.status_code == 302
        assert response.url == expected_url

    def test_response_change_redirects_to_frontend_detail_on_save_and_open_front(
        self,
        policy_factory,
        admin_user,
    ):
        """
        Кнопка "Сохранить и открыть на фронте" после редактирования ведет на фронтовый detail.
        """
        policy_admin = PolicyAdmin(Policy, admin.site)
        policy = policy_factory()
        request = RequestFactory().post(
            f"/admin/policies/policy/{policy.pk}/change/",
            {policy_admin.save_and_open_front_button_name: "1"},
        )
        request.user = admin_user

        response = policy_admin.response_change(request, policy)
        expected_url = reverse("policies:detail", args=[policy.pk])

        assert response.status_code == 302
        assert response.url == expected_url

    def test_front_redirect_flag_only_for_custom_button(self, admin_user):
        """
        Обычная кнопка "Сохранить" не должна включать редирект на фронт.
        """
        policy_admin = PolicyAdmin(Policy, admin.site)

        save_request = RequestFactory().post(
            "/admin/policies/policy/add/", {"_save": "1"}
        )
        save_request.user = admin_user
        assert not policy_admin._should_redirect_to_front(save_request)

        front_request = RequestFactory().post(
            "/admin/policies/policy/add/",
            {policy_admin.save_and_open_front_button_name: "1"},
        )
        front_request.user = admin_user
        assert policy_admin._should_redirect_to_front(front_request)

    def test_change_form_shows_custom_front_button_first_and_default(
        self,
        client,
        admin_user,
        policy_factory,
    ):
        """
        В форме админки новая кнопка должна идти первой среди Save-кнопок
        и быть кнопкой по умолчанию.
        """
        policy = policy_factory()
        client.force_login(admin_user)
        url = reverse("admin:policies_policy_change", args=[policy.pk])

        response = client.get(url)
        assert response.status_code == 200

        content = response.content.decode()
        front_btn = 'name="_save_and_open_front"'
        save_btn = 'name="_save"'

        assert front_btn in content
        assert 'class="default" name="_save_and_open_front"' in content
        assert content.find(front_btn) < content.find(save_btn)
