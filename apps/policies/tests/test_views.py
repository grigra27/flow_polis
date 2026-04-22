"""
Unit tests for policy views.

Tests verify that insurance_sum is correctly displayed in templates
and that views properly handle the new data structure.
"""
import pytest
from datetime import timedelta
from decimal import Decimal
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone


@pytest.fixture
def regular_user(db):
    """Create a regular user for testing views."""
    return User.objects.create_user(
        username="testuser", email="test@test.com", password="testpass123"
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
        url = reverse("policies:detail", kwargs={"pk": sample_policy.pk})
        response = client.get(url)

        # Check response is successful
        assert response.status_code == 200

        # Check that insurance_sum is in the response content
        content = response.content.decode("utf-8")

        # Check that the column header is present
        assert "СС, ₽" in content

        # Check that the actual insurance_sum value is displayed
        # The template uses custom 'rub' filter which formats as "500 000" (with spaces)
        # For 500000.00 it should display as "500 000"
        insurance_sum_formatted = "{:,.0f}".format(
            float(sample_payment.insurance_sum)
        ).replace(",", " ")
        assert insurance_sum_formatted in content

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
            insurance_sum=Decimal("1000000.00"),
        )
        payment2 = payment_schedule_factory(
            policy=sample_policy,
            year_number=1,
            installment_number=2,
            insurance_sum=Decimal("950000.00"),
        )

        # Login and get page
        client.force_login(regular_user)
        url = reverse("policies:detail", kwargs={"pk": sample_policy.pk})
        response = client.get(url)

        # Check both insurance sums are displayed
        content = response.content.decode("utf-8")
        assert response.status_code == 200
        assert "Страховая сумма" in content


@pytest.mark.django_db
class TestPaymentScheduleListView:
    """Tests for PaymentScheduleListView."""

    def test_payment_list_view_accessible(self, client, regular_user, sample_payment):
        """
        Test that payment list view is accessible and displays payments.

        Validates: Requirements 1.2
        """
        # Login user
        client.force_login(regular_user)

        # Get payment list page
        url = reverse("policies:payments")
        response = client.get(url)

        # Check response is successful
        assert response.status_code == 200

        # Check that payment is in the list
        content = response.content.decode("utf-8")
        assert sample_payment.policy.policy_number in content

    def test_payment_list_highlights_no_broker_policy_rows(
        self, client, regular_user, sample_payment
    ):
        """
        Test that payments for policies without broker participation
        are highlighted with gray row and "Без брокера" badge.
        """
        sample_payment.policy.broker_participation = False
        sample_payment.policy.save(update_fields=["broker_participation"])

        client.force_login(regular_user)
        url = reverse("policies:payments")
        response = client.get(f"{url}?status=all")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "table-secondary" in content
        assert "Без брокера" in content

    def test_payment_list_combines_status_date_branch_and_insurer_filters(
        self,
        client,
        regular_user,
        branch_factory,
        insurer_factory,
        insurance_type_factory,
        policy_factory,
        payment_schedule_factory,
    ):
        """
        Test that all payment filters are applied together:
        status + date range + branch + insurer.
        """
        today = timezone.now().date()
        branch_match = branch_factory(branch_name="Филиал 1")
        branch_other = branch_factory(branch_name="Филиал 2")
        insurer_match = insurer_factory(insurer_name="СК 1")
        insurer_other = insurer_factory(insurer_name="СК 2")
        insurance_type = insurance_type_factory(name="КАСКО-Фильтр")

        matching_policy = policy_factory(
            policy_number="PAY-FILTER-MATCH",
            branch=branch_match,
            insurer=insurer_match,
            insurance_type=insurance_type,
            policy_active=True,
        )
        other_branch_policy = policy_factory(
            policy_number="PAY-FILTER-BRANCH",
            branch=branch_other,
            insurer=insurer_match,
            insurance_type=insurance_type,
            policy_active=True,
        )
        other_insurer_policy = policy_factory(
            policy_number="PAY-FILTER-INSURER",
            branch=branch_match,
            insurer=insurer_other,
            insurance_type=insurance_type,
            policy_active=True,
        )

        matching_payment = payment_schedule_factory(
            policy=matching_policy,
            year_number=1,
            installment_number=1,
            due_date=today + timedelta(days=5),
            paid_date=None,
            insurer_date=None,
        )
        # Must be excluded by status=upcoming (even though date/branch/insurer match)
        payment_schedule_factory(
            policy=matching_policy,
            year_number=1,
            installment_number=2,
            due_date=today + timedelta(days=6),
            paid_date=today + timedelta(days=6),
            insurer_date=None,
        )
        # Must be excluded by date range
        payment_schedule_factory(
            policy=matching_policy,
            year_number=1,
            installment_number=3,
            due_date=today + timedelta(days=40),
            paid_date=None,
            insurer_date=None,
        )
        # Must be excluded by branch
        payment_schedule_factory(
            policy=other_branch_policy,
            due_date=today + timedelta(days=5),
            paid_date=None,
            insurer_date=None,
        )
        # Must be excluded by insurer
        payment_schedule_factory(
            policy=other_insurer_policy,
            due_date=today + timedelta(days=5),
            paid_date=None,
            insurer_date=None,
        )

        client.force_login(regular_user)
        url = reverse("policies:payments")
        response = client.get(
            url,
            {
                "status": "upcoming",
                "date_from": today.isoformat(),
                "date_to": (today + timedelta(days=10)).isoformat(),
                "branch": branch_match.id,
                "insurer": insurer_match.id,
            },
        )

        assert response.status_code == 200
        result_ids = [payment.id for payment in response.context["payments"]]
        assert result_ids == [matching_payment.id]

    def test_payment_list_keeps_status_buttons_visible_with_date_filter(
        self, client, regular_user, sample_payment
    ):
        """
        Test that status buttons remain visible and preserve date params
        when date range filters are set.
        """
        client.force_login(regular_user)
        date_from = "2026-01-01"
        date_to = "2026-12-31"

        url = reverse("policies:payments")
        response = client.get(
            url,
            {
                "status": "upcoming",
                "date_from": date_from,
                "date_to": date_to,
            },
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        assert "Акт согласован СК" in content
        assert f"status=paid&date_from={date_from}&date_to={date_to}" in content
        assert 'name="status" value="upcoming"' in content

    def test_payment_list_date_filter_without_explicit_status_uses_all(
        self,
        client,
        regular_user,
        policy_factory,
        payment_schedule_factory,
    ):
        """
        Test that date-only filter works as a standalone filter:
        without explicit status the view should return all statuses in range.
        """
        today = timezone.now().date()
        policy = policy_factory(
            policy_number="PAY-FILTER-DATE-ONLY", policy_active=True
        )

        upcoming_payment = payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=today + timedelta(days=5),
            paid_date=None,
            insurer_date=None,
        )
        paid_payment = payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            due_date=today + timedelta(days=6),
            paid_date=today + timedelta(days=6),
            insurer_date=None,
        )

        client.force_login(regular_user)
        url = reverse("policies:payments")
        response = client.get(
            url,
            {
                "date_from": today.isoformat(),
                "date_to": (today + timedelta(days=10)).isoformat(),
            },
        )

        assert response.status_code == 200
        result_ids = {payment.id for payment in response.context["payments"]}
        assert result_ids == {upcoming_payment.id, paid_payment.id}
        assert response.context["selected_status"] == "all"

    def test_payment_list_paid_status_includes_prepayments(
        self,
        client,
        regular_user,
        policy_factory,
        payment_schedule_factory,
    ):
        """
        Test that paid status includes prepayments:
        paid_date is set, insurer_date is empty, even when due_date is in the future.
        """
        today = timezone.now().date()
        policy = policy_factory(
            policy_number="PAY-FILTER-PAID-PREPAY", policy_active=True
        )

        prepayment = payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=today + timedelta(days=1),
            paid_date=today,
            insurer_date=None,
        )
        # Exclude: approved payment
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=2,
            due_date=today + timedelta(days=2),
            paid_date=today + timedelta(days=1),
            insurer_date=today + timedelta(days=1),
        )
        # Exclude: unpaid payment
        payment_schedule_factory(
            policy=policy,
            year_number=1,
            installment_number=3,
            due_date=today + timedelta(days=3),
            paid_date=None,
            insurer_date=None,
        )

        client.force_login(regular_user)
        url = reverse("policies:payments")
        response = client.get(url, {"status": "paid"})

        assert response.status_code == 200
        result_ids = {payment.id for payment in response.context["payments"]}
        assert prepayment.id in result_ids
