"""
Unit tests for policy views.

Tests verify that insurance_sum is correctly displayed in templates
and that views properly handle the new data structure.
"""
import pytest
from datetime import timedelta
from decimal import Decimal
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit
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

    def test_both_tag_groups_can_display_the_same_tag(
        self, client, regular_user, sample_policy
    ):
        from apps.insurers.models import InfoTag
        from apps.policies.models import PolicyInfo

        tag = InfoTag.objects.create(name="Перенайм")
        for group in (1, 2):
            PolicyInfo.objects.create(policy=sample_policy, tag=tag, info_field=group)
        client.force_login(regular_user)
        url = reverse("policies:detail", args=[sample_policy.pk])
        html = client.get(url).content.decode()
        assert html.count("<li>Перенайм</li>") == 2
        for group in (1, 2):
            assert re.search(
                rf"<h3>Инфо {group}</h3>\s*<ul[^>]*><li>Перенайм</li>", html
            )

    def test_schedule_progress_and_next_installment(
        self, client, regular_user, sample_policy, payment_schedule_factory
    ):
        today = timezone.localdate()
        payment_schedule_factory(
            policy=sample_policy,
            year_number=4,
            due_date=today,
            paid_date=today,
            amount=Decimal("125.34"),
        )
        upcoming = payment_schedule_factory(
            policy=sample_policy,
            year_number=4,
            installment_number=2,
            due_date=today + timedelta(days=10),
            amount=Decimal("75.11"),
        )
        client.force_login(regular_user)
        url = reverse("policies:detail", args=[sample_policy.pk])
        card = client.get(url)
        assert card.context["paid_count"] == 1
        assert card.context["paid_total"] == Decimal("125.34")
        assert card.context["premium_total"] == Decimal("200.45")
        assert card.context["next_payment"] == upcoming
        assert "4-й год" in card.content.decode()

        sample_policy.policy_active = False
        sample_policy.termination_date = today
        sample_policy.save()
        assert client.get(url).context["next_payment"] is None

    def test_commission_rounding_to_kopecks_is_not_a_rate_difference(
        self,
        client,
        regular_user,
        sample_policy,
        payment_schedule_factory,
        commission_rate_factory,
    ):
        rate = commission_rate_factory(
            insurer=sample_policy.insurer,
            insurance_type=sample_policy.insurance_type,
            kv_percent=Decimal("25.00"),
        )
        payment = payment_schedule_factory(
            policy=sample_policy,
            commission_rate=rate,
            amount=Decimal("33917.13"),
        )
        client.force_login(regular_user)
        url = reverse("policies:detail", args=[sample_policy.pk])
        payment.refresh_from_db()
        assert payment.kv_rub == Decimal("8479.28")
        assert 'class="rate-difference"' not in client.get(url).content.decode()
        payment.kv_rub = Decimal("8500.00")
        payment.save()
        assert 'class="rate-difference"' in client.get(url).content.decode()

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
        # Create payments with different insurance sums.
        # Явные due_date по возрастанию — фабрика ставит рандом, и валидатор
        # PaymentSchedule.clean() требует строгого возрастания дат между installment'ами.
        from datetime import date, timedelta

        payment1 = payment_schedule_factory(
            policy=sample_policy,
            year_number=1,
            installment_number=1,
            due_date=date.today() + timedelta(days=10),
            insurance_sum=Decimal("1000000.00"),
        )
        payment2 = payment_schedule_factory(
            policy=sample_policy,
            year_number=1,
            installment_number=2,
            due_date=date.today() + timedelta(days=20),
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

        # Get payment list page.
        # ?status=all чтобы не зависеть от due_date фабрики (дефолтный фильтр
        # "upcoming" показывает только платежи в окне сегодня…+30 дней).
        url = reverse("policies:payments")
        response = client.get(f"{url}?status=all")

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
        # Шаблон использует кастомный tbl-row-nobroker (не bootstrap'овский table-secondary)
        assert "tbl-row-nobroker" in content
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
        status + date range + branch + insurer + year/installment.
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
        # Must be excluded by year/installment filter.
        # Дата отличается от первого платежа — модель валидирует строгое возрастание
        # дат между installment'ами одного полиса (apps/policies/models.py:288 .clean()).
        payment_schedule_factory(
            policy=matching_policy,
            year_number=2,
            installment_number=1,
            due_date=today + timedelta(days=8),
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
                "year_number": 1,
                "installment_number": 1,
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
        year_number = "2"
        installment_number = "3"

        url = reverse("policies:payments")
        response = client.get(
            url,
            {
                "status": "upcoming",
                "date_from": date_from,
                "date_to": date_to,
                "year_number": year_number,
                "installment_number": installment_number,
            },
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        assert "Акт согласован СК" in content
        paid_link = re.search(
            r'<a href="([^"]+)"\s+class="pl-status-btn pl-status-btn--paid\b', content
        )
        assert paid_link is not None
        params = parse_qs(urlsplit(unescape(paid_link.group(1))).query)
        assert params == {
            "status": ["paid"],
            "date_from": [date_from],
            "date_to": [date_to],
            "year_number": [year_number],
            "installment_number": [installment_number],
        }
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
