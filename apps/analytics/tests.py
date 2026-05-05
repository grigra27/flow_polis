from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.analytics.services import AnalyticsService
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy


class AnalyticsServiceQueryOptimizationTest(TestCase):
    """Проверка, что ключевые аналитические методы не деградируют в N+1."""

    def setUp(self):
        self.service = AnalyticsService()

        insurance_type = InsuranceType.objects.create(name="КАСКО")

        for idx in range(1, 4):
            client = Client.objects.create(
                client_name=f"Клиент {idx}",
                client_inn=f"12345678{idx:02d}",
            )
            insurer = Insurer.objects.create(insurer_name=f"Страховщик {idx}")
            branch = Branch.objects.create(branch_name=f"Филиал {idx}")

            policy = Policy.objects.create(
                policy_number=f"POL-{idx}",
                dfa_number=f"DFA-{idx}",
                client=client,
                insurer=insurer,
                branch=branch,
                insurance_type=insurance_type,
                property_description="Тестовое имущество",
                start_date=date(2024, 1, idx),
                end_date=date(2024, 12, idx),
                policy_active=True,
                broker_participation=True,
            )

            PaymentSchedule.objects.create(
                policy=policy,
                year_number=1,
                installment_number=1,
                due_date=date(2024, 2, idx),
                insurance_sum=Decimal("100000.00"),
                amount=Decimal("10000.00"),
                kv_rub=Decimal("1000.00"),
            )

    def test_get_branch_analytics_runs_in_bounded_queries(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.service.get_branch_analytics()

        self.assertEqual(data["total_branches"], 3)
        self.assertLessEqual(len(queries), 6)

    def test_get_insurer_analytics_runs_in_bounded_queries(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.service.get_insurer_analytics()

        self.assertEqual(data["total_insurers"], 3)
        self.assertLessEqual(len(queries), 6)

    def test_get_client_analytics_runs_in_bounded_queries(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.service.get_client_analytics()

        self.assertEqual(data["total_clients"], 3)
        self.assertLessEqual(len(queries), 7)

    def test_get_top_insurers_table_runs_in_bounded_queries(self):
        with CaptureQueriesContext(connection) as queries:
            rows = self.service.get_top_insurers_table(limit=10)

        self.assertEqual(len(rows), 3)
        self.assertLessEqual(len(queries), 6)

    def test_group_analytics_count_max_insurance_sum_once_per_policy(self):
        policy = Policy.objects.get(policy_number="POL-1")
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=2,
            installment_number=1,
            due_date=date(2025, 2, 1),
            insurance_sum=Decimal("90000.00"),
            amount=Decimal("20000.00"),
            kv_rub=Decimal("2000.00"),
        )
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=3,
            installment_number=1,
            due_date=date(2026, 2, 1),
            insurance_sum=Decimal("80000.00"),
            amount=Decimal("30000.00"),
            kv_rub=Decimal("3000.00"),
        )

        branch_data = self.service.get_branch_analytics()
        branch_metric = next(
            metric
            for metric in branch_data["branch_metrics"]
            if metric["branch"]["id"] == policy.branch_id
        )
        self.assertEqual(branch_metric["insurance_sum"], Decimal("100000.00"))
        self.assertEqual(branch_metric["premium_volume"], Decimal("60000.00"))

        insurer_data = self.service.get_insurer_analytics()
        insurer_metric = next(
            metric
            for metric in insurer_data["insurer_metrics"]
            if metric["insurer"].id == policy.insurer_id
        )
        self.assertEqual(insurer_metric["insurance_sum"], Decimal("100000.00"))
        self.assertEqual(insurer_metric["premium_volume"], Decimal("60000.00"))

        client_data = self.service.get_client_analytics()
        client_metric = next(
            metric
            for metric in client_data["all_client_metrics"]
            if metric["client"]["id"] == policy.client_id
        )
        self.assertEqual(client_metric["insurance_sum"], Decimal("100000.00"))
        self.assertEqual(client_metric["premium_volume"], Decimal("60000.00"))

    def test_dashboard_metrics_bridge_insurance_sum_counts_policy_once(self):
        policy = Policy.objects.get(policy_number="POL-1")
        current_month_start = timezone.localdate().replace(day=1)
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=2,
            installment_number=1,
            due_date=current_month_start - timedelta(days=1),
            insurance_sum=Decimal("1000000.00"),
            amount=Decimal("10000.00"),
            kv_rub=Decimal("1000.00"),
            paid_date=current_month_start - timedelta(days=1),
        )
        PaymentSchedule.objects.create(
            policy=policy,
            year_number=3,
            installment_number=1,
            due_date=current_month_start + timedelta(days=30),
            insurance_sum=Decimal("900000.00"),
            amount=Decimal("20000.00"),
            kv_rub=Decimal("2000.00"),
        )

        metrics = self.service.get_dashboard_metrics()

        self.assertEqual(metrics["actual_insurance_sum"], Decimal("1000000.00"))
        self.assertEqual(metrics["planned_insurance_sum"], Decimal("1000000.00"))
        self.assertEqual(metrics["total_insurance_sum"], Decimal("1000000.00"))

    def test_get_branch_portfolio_analytics_v2_returns_expected_shape(self):
        data = self.service.get_branch_portfolio_analytics_v2(horizon_months=12)

        self.assertIn("summary", data)
        self.assertIn("branch_metrics", data)
        self.assertIn("branch_drilldown", data)
        self.assertEqual(data["summary"]["total_branches"], 3)
        self.assertEqual(data["summary"]["total_active_policies"], 3)
        self.assertEqual(len(data["branch_metrics"]), 3)

    def test_get_branch_portfolio_analytics_v2_runs_in_bounded_queries(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.service.get_branch_portfolio_analytics_v2(horizon_months=12)

        self.assertEqual(data["summary"]["total_branches"], 3)
        self.assertLessEqual(len(queries), 10)
