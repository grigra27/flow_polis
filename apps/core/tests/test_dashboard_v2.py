from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Max, Q, Sum
from django.db.models.functions import Coalesce
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
        inactive_branch = Branch.objects.create(branch_name="Неактивный филиал")
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
            franchise=Decimal("0"),
            policy_active=True,
            policy_uploaded=True,
            broker_participation=True,
            termination_date=today - timedelta(days=2),
        )

        policy_inactive = Policy.objects.create(
            policy_number="P-004",
            dfa_number="DFA-004",
            client=leasing_client,
            insurer=insurer,
            branch=inactive_branch,
            insurance_type=insurance_type,
            property_description="Оборудование",
            start_date=today - timedelta(days=90),
            end_date=today + timedelta(days=120),
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
            policy=policy_inactive,
            year_number=1,
            installment_number=1,
            due_date=today + timedelta(days=5),
            amount=Decimal("99999.00"),
            insurance_sum=Decimal("9999999.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("999.99"),
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
            "dashboard_v2_snapshot",
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
            "dashboard_v2_legacy_relay",
        }
        self.assertTrue(expected_keys.issubset(context.keys()))
        self.assertEqual(context["dashboard_v2_structure_scope"], "all")

        health = context["dashboard_v2_health"]
        self.assertGreaterEqual(health["score"], Decimal("0"))
        self.assertLessEqual(health["score"], Decimal("100"))
        self.assertEqual(len(health["components"]), 4)

        snapshot = context["dashboard_v2_snapshot"]
        self.assertEqual(len(snapshot["cards"]), 4)
        self.assertGreaterEqual(snapshot["active_policies_count"], 1)

        contour = context["dashboard_v2_payment_contour"]
        self.assertEqual(len(contour["statuses"]), 3)

        bridge = context["dashboard_v2_bridge"]
        current_month_start = timezone.localdate().replace(day=1)
        self.assertIn("calendar_year", bridge)
        self.assertIn("year_start", bridge)
        self.assertIn("year_end", bridge)
        self.assertTrue(
            bridge["planned_period_label"].startswith(
                current_month_start.strftime("%d.%m.%Y")
            )
        )
        self.assertNotIn("commission", bridge["actual"])
        self.assertNotIn("commission", bridge["planned"])
        self.assertNotIn("commission", bridge["bridge"])

        aging = context["dashboard_v2_aging"]
        self.assertGreaterEqual(aging["total_count"], 1)

        data_quality = context["dashboard_v2_data_quality"]
        self.assertEqual(len(data_quality["problems"]), 3)

        structure = context["dashboard_v2_structure"]
        self.assertEqual(structure["policy_count"], 2)
        self.assertIn("branch_breakdown", structure)
        self.assertIn("insurer_breakdown", structure)
        self.assertIn("type_breakdown", structure)
        self.assertGreaterEqual(len(structure["branch_breakdown"]["top"]), 1)
        self.assertGreaterEqual(len(structure["branch_breakdown"]["chart"]), 1)
        self.assertTrue(
            structure["branch_breakdown"]["pie_css"].startswith("conic-gradient(")
        )
        self.assertIn("color", structure["branch_breakdown"]["chart"][0])
        branch_names = [row["name"] for row in structure["by_branch"]]
        self.assertNotIn("Неактивный филиал", branch_names)

        insights = context["dashboard_v2_insights"]
        self.assertGreaterEqual(len(insights["quick_actions"]), 1)

        legacy_relay = context["dashboard_v2_legacy_relay"]
        self.assertEqual(len(legacy_relay["cards"]), 4)
        self.assertEqual(legacy_relay["cards"][0]["title"], "Предстоящие платежи")
        self.assertIn("link_url", legacy_relay["cards"][0])

    def test_structure_scope_broker_filters_non_broker_policies(self):
        context_all = DashboardV2Service().get_dashboard_context(structure_scope="all")
        context_broker = DashboardV2Service().get_dashboard_context(
            structure_scope="broker"
        )

        self.assertEqual(context_all["dashboard_v2_structure_scope"], "all")
        self.assertEqual(context_broker["dashboard_v2_structure_scope"], "broker")

        all_structure = context_all["dashboard_v2_structure"]
        broker_structure = context_broker["dashboard_v2_structure"]

        self.assertEqual(all_structure["policy_count"], 2)
        self.assertEqual(broker_structure["policy_count"], 1)

        all_sum = all_structure["by_branch"][0]["bridge_insurance_sum"]
        broker_sum = broker_structure["by_branch"][0]["bridge_insurance_sum"]

        current_month_start = timezone.localdate().replace(day=1)
        non_broker_qs = PaymentSchedule.objects.filter(
            policy__policy_active=True,
            policy__broker_participation=False,
        )
        expected_non_broker_sum = sum(
            (
                row["policy_max"] or Decimal("0")
                for row in non_broker_qs.values("policy_id").annotate(
                    policy_max=Max("insurance_sum")
                )
            ),
            Decimal("0"),
        )
        self.assertEqual(all_sum - broker_sum, expected_non_broker_sum)

        all_premium = all_structure["top_branch_premium"]["bridge_insurance_sum"]
        broker_premium = broker_structure["top_branch_premium"]["bridge_insurance_sum"]
        expected_non_broker_premium = non_broker_qs.filter(
            Q(due_date__lt=current_month_start, paid_date__isnull=False)
            | Q(due_date__gte=current_month_start)
        ).aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]
        self.assertEqual(all_premium - broker_premium, expected_non_broker_premium)

    def test_structure_filters_inactive_dfa_policies(self):
        today = timezone.localdate()
        current_month_start = today.replace(day=1)
        client = Client.objects.create(
            client_name="ООО Неактивный ДФА",
            client_inn="1122334455",
        )
        insurer = Insurer.objects.get(insurer_name="СК Тест")
        branch = Branch.objects.create(branch_name="Филиал неактивного ДФА")
        insurance_type = InsuranceType.objects.get(name="КАСКО")
        commission_rate = CommissionRate.objects.get(
            insurer=insurer,
            insurance_type=insurance_type,
        )
        policy = Policy.objects.create(
            policy_number="P-INACTIVE-DFA",
            dfa_number="DFA-INACTIVE",
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Объект с неактивным ДФА",
            start_date=today - timedelta(days=10),
            end_date=today + timedelta(days=300),
            franchise=Decimal("0"),
            policy_active=True,
            policy_uploaded=True,
            broker_participation=True,
            dfa_active=False,
        )
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=current_month_start + timedelta(days=1),
            amount=Decimal("999999.00"),
            insurance_sum=Decimal("9999999.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("99999.00"),
            paid_date=None,
        )

        context = DashboardV2Service().get_dashboard_context()
        structure = context["dashboard_v2_structure"]

        self.assertEqual(context["dashboard_v2_snapshot"]["active_policies_count"], 3)
        self.assertEqual(structure["policy_count"], 2)
        self.assertNotIn(
            branch.branch_name,
            [row["name"] for row in structure["by_branch"]],
        )
        self.assertNotIn(
            branch.branch_name,
            [row["name"] for row in structure["branch_breakdown_premium"]["chart"]],
        )

    def test_structure_counts_one_max_insurance_sum_per_policy(self):
        today = timezone.localdate()
        current_month_start = today.replace(day=1)
        client = Client.objects.create(
            client_name="ООО Многолетний Клиент",
            client_inn="9876543210",
        )
        insurer = Insurer.objects.get(insurer_name="СК Тест")
        branch = Branch.objects.create(branch_name="Многолетний филиал")
        insurance_type = InsuranceType.objects.get(name="КАСКО")
        commission_rate = CommissionRate.objects.get(
            insurer=insurer,
            insurance_type=insurance_type,
        )
        policy = Policy.objects.create(
            policy_number="P-MULTI",
            dfa_number="DFA-MULTI",
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Многолетний объект",
            start_date=current_month_start - timedelta(days=30),
            end_date=current_month_start + timedelta(days=900),
            franchise=Decimal("0"),
            policy_active=True,
            policy_uploaded=True,
            broker_participation=True,
        )

        PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=current_month_start - timedelta(days=1),
            amount=Decimal("10000.00"),
            insurance_sum=Decimal("1000000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("1000.00"),
            paid_date=current_month_start - timedelta(days=1),
        )
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=2,
            installment_number=1,
            due_date=current_month_start + timedelta(days=180),
            amount=Decimal("20000.00"),
            insurance_sum=Decimal("900000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("2000.00"),
            paid_date=None,
        )
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=3,
            installment_number=1,
            due_date=current_month_start + timedelta(days=540),
            amount=Decimal("30000.00"),
            insurance_sum=Decimal("800000.00"),
            commission_rate=commission_rate,
            kv_rub=Decimal("3000.00"),
            paid_date=None,
        )

        structure = DashboardV2Service().get_dashboard_context()[
            "dashboard_v2_structure"
        ]
        branch_sum_row = next(
            row for row in structure["by_branch"] if row["name"] == branch.branch_name
        )
        branch_premium_row = next(
            row
            for row in structure["branch_breakdown_premium"]["top"]
            if row["name"] == branch.branch_name
        )

        self.assertEqual(branch_sum_row["bridge_insurance_sum"], Decimal("1000000.00"))
        self.assertEqual(
            branch_premium_row["bridge_insurance_sum"], Decimal("60000.00")
        )


class DashboardV2ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="dashboard-user",
            email="dashboard@example.com",
            password="test-pass-123",
        )

    def test_dashboard_v2_requires_login(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_dashboard_v2_renders_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Дашборд версия 2.0")
        self.assertContains(response, "Ключевые списки из основного дашборда")
        self.assertContains(response, "Все сделки")
        self.assertContains(response, "Только с участием брокера")
        self.assertIn("dashboard_v2_health", response.context)
        self.assertIn("dashboard_v2_insights", response.context)
        self.assertEqual(response.context["dashboard_v2_structure_scope"], "all")

    def test_dashboard_v2_accepts_structure_scope_query_param(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("core:dashboard"), {"structure_scope": "broker"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_v2_structure_scope"], "broker")

    def test_exports_page_does_not_contain_dashboard_v2_link(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("reports:index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Дашборд версия 2.0")
