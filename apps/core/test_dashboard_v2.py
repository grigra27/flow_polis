from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.core.services.dashboard_v2_service import DashboardV2Service
from apps.insurers.models import Branch, CommissionRate, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy


class DashboardV2ServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()

        leasing_client = Client.objects.create(
            client_name="ООО Тестовый Клиент",
            client_inn="1234567890",
        )

        insurer = Insurer.objects.create(insurer_name="СК Тест")
        branch = Branch.objects.create(branch_name="Москва")
        insurance_type = InsuranceType.objects.create(name="КАСКО")

        commission_rate = CommissionRate.objects.create(
            insurer=insurer,
            insurance_type=insurance_type,
            kv_percent=Decimal("10.00"),
        )

        policy_active_ok = Policy.objects.create(
            policy_number="P-001",
            dfa_number="DFA-001",
            client=leasing_client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Автомобиль",
            start_date=today - timedelta(days=120),
            end_date=today + timedelta(days=20),
            premium_total=Decimal("2500.00"),
            franchise=Decimal("0"),
            policy_active=True,
            policy_uploaded=True,
            broker_participation=True,
        )

        policy_active_risky = Policy.objects.create(
            policy_number="P-002",
            dfa_number="DFA-002",
            client=leasing_client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Грузовик",
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=75),
            premium_total=Decimal("4200.00"),
            franchise=Decimal("0"),
            policy_active=True,
            policy_uploaded=False,
            broker_participation=False,
        )

        policy_active_conflict = Policy.objects.create(
            policy_number="P-003",
            dfa_number="DFA-003",
            client=leasing_client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Спецтехника",
            start_date=today - timedelta(days=80),
            end_date=today + timedelta(days=50),
            premium_total=Decimal("3100.00"),
            franchise=Decimal("0"),
            policy_active=True,
            policy_uploaded=True,
            broker_participation=True,
            termination_date=today - timedelta(days=2),
        )

        Policy.objects.create(
            policy_number="P-004",
            dfa_number="DFA-004",
            client=leasing_client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Оборудование",
            start_date=today - timedelta(days=90),
            end_date=today + timedelta(days=120),
            premium_total=Decimal("900.00"),
            franchise=Decimal("0"),
            policy_active=False,
            policy_uploaded=False,
            broker_participation=True,
            termination_date=None,
        )

        PaymentSchedule.objects.create(
            policy=policy_active_ok,
            year_number=1,
            installment_number=1,
            due_date=today - timedelta(days=10),
            amount=Decimal("1000.00"),
            insurance_sum=Decimal("10000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("100.00"),
            paid_date=today - timedelta(days=8),
        )
        PaymentSchedule.objects.create(
            policy=policy_active_ok,
            year_number=1,
            installment_number=2,
            due_date=today + timedelta(days=10),
            amount=Decimal("1500.00"),
            insurance_sum=Decimal("10000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("150.00"),
            paid_date=None,
        )

        PaymentSchedule.objects.create(
            policy=policy_active_risky,
            year_number=1,
            installment_number=1,
            due_date=today - timedelta(days=20),
            amount=Decimal("2000.00"),
            insurance_sum=Decimal("12000.00"),
            commission_rate=None,
            kv_rub=Decimal("200.00"),
            paid_date=None,
        )
        PaymentSchedule.objects.create(
            policy=policy_active_risky,
            year_number=1,
            installment_number=2,
            due_date=today + timedelta(days=40),
            amount=Decimal("2200.00"),
            insurance_sum=Decimal("12000.00"),
            commission_rate=None,
            kv_rub=Decimal("220.00"),
            paid_date=None,
        )

        PaymentSchedule.objects.create(
            policy=policy_active_conflict,
            year_number=1,
            installment_number=1,
            due_date=today - timedelta(days=95),
            amount=Decimal("1800.00"),
            insurance_sum=Decimal("9000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("180.00"),
            paid_date=None,
        )
        PaymentSchedule.objects.create(
            policy=policy_active_conflict,
            year_number=1,
            installment_number=2,
            due_date=today + timedelta(days=15),
            amount=Decimal("1300.00"),
            insurance_sum=Decimal("9000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("130.00"),
            paid_date=None,
        )

    def test_service_returns_full_context(self):
        context = DashboardV2Service().get_dashboard_context()

        expected_keys = {
            "dashboard_v2_meta",
            "dashboard_v2_health",
            "dashboard_v2_bridge",
            "dashboard_v2_payment_contour",
            "dashboard_v2_aging",
            "dashboard_v2_renewal",
            "dashboard_v2_data_quality",
            "dashboard_v2_structure",
            "dashboard_v2_concentration",
            "dashboard_v2_dynamics",
            "dashboard_v2_insights",
        }
        self.assertTrue(expected_keys.issubset(context.keys()))

        health = context["dashboard_v2_health"]
        self.assertGreaterEqual(health["score"], Decimal("0"))
        self.assertLessEqual(health["score"], Decimal("100"))
        self.assertEqual(len(health["components"]), 4)

        contour = context["dashboard_v2_payment_contour"]
        self.assertEqual(len(contour["statuses"]), 3)

        aging = context["dashboard_v2_aging"]
        self.assertGreaterEqual(aging["total_count"], 1)

        data_quality = context["dashboard_v2_data_quality"]
        self.assertEqual(len(data_quality["problems"]), 3)

        insights = context["dashboard_v2_insights"]
        self.assertGreaterEqual(len(insights["quick_actions"]), 1)


class DashboardV2ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="dashboard-user",
            email="dashboard@example.com",
            password="test-pass-123",
        )

    def test_dashboard_v2_requires_login(self):
        response = self.client.get(reverse("core:dashboard_v2"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_dashboard_v2_renders_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:dashboard_v2"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Дашборд версия 2.0")
        self.assertIn("dashboard_v2_health", response.context)
        self.assertIn("dashboard_v2_insights", response.context)

    def test_exports_page_contains_dashboard_v2_link(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("reports:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Дашборд версия 2.0")
        self.assertContains(response, reverse("core:dashboard_v2"))
