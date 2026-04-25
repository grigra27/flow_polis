from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client as DjangoClient
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from apps.clients.models import Client as LeasingClient
from apps.policies.models import Policy

from .models import (
    Branch,
    CommissionRate,
    InfoTag,
    InsuranceType,
    Insurer,
    LeasingManager,
)
from .services import BranchStatisticsService, InsurerStatisticsService
from .templatetags.insurer_tags import (
    branch_logo,
    insurance_type_icon,
    insurer_logo,
    ru_pluralize,
    update_query,
)

User = get_user_model()


class InsurerStatisticsTestDataMixin:
    def setUp_statistics_data(self):
        cache.clear()

        self.insurer = Insurer.objects.create(insurer_name="Тестовая СК")
        self.branch_a = Branch.objects.create(branch_name="Филиал А")
        self.branch_b = Branch.objects.create(branch_name="Филиал Б")
        self.type_casco = InsuranceType.objects.create(name="КАСКО")
        self.type_osago = InsuranceType.objects.create(name="ОСАГО")
        self.leasing_client = LeasingClient.objects.create(
            client_name="Тестовый лизингополучатель", client_inn="7701234567"
        )

        self.policy_a1 = self._create_policy(
            policy_number="POL-001",
            branch=self.branch_a,
            insurance_type=self.type_casco,
            premium=Decimal("1000.00"),
            start_date=date(2026, 1, 10),
            end_date=date(2027, 1, 9),
            policy_active=True,
            broker_participation=True,
        )
        self.policy_a2 = self._create_policy(
            policy_number="POL-002",
            branch=self.branch_a,
            insurance_type=self.type_osago,
            premium=Decimal("4000.00"),
            start_date=date(2025, 6, 10),
            end_date=date(2026, 6, 9),
            policy_active=False,
            broker_participation=False,
        )
        self.policy_b1 = self._create_policy(
            policy_number="POL-003",
            branch=self.branch_b,
            insurance_type=self.type_casco,
            premium=Decimal("9000.00"),
            start_date=date(2026, 3, 1),
            end_date=date(2027, 2, 28),
            policy_active=True,
            broker_participation=True,
        )

    def _create_policy(
        self,
        *,
        policy_number,
        branch,
        insurance_type,
        premium,
        start_date,
        end_date,
        policy_active,
        broker_participation,
        insurer=None,
    ):
        return Policy.objects.create(
            policy_number=policy_number,
            dfa_number=f"DFA-{policy_number}",
            client=self.leasing_client,
            insurer=insurer or self.insurer,
            property_description="Тестовое имущество",
            start_date=start_date,
            end_date=end_date,
            insurance_type=insurance_type,
            branch=branch,
            policy_active=policy_active,
            broker_participation=broker_participation,
        )


class CommissionRateAPITest(TestCase):
    """Tests for commission rate API endpoint"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testadmin", password="testpass123", is_staff=True
        )

        self.insurer = Insurer.objects.create(insurer_name="Тестовая СК")
        self.insurance_type = InsuranceType.objects.create(name="КАСКО")
        self.commission_rate = CommissionRate.objects.create(
            insurer=self.insurer,
            insurance_type=self.insurance_type,
            kv_percent=Decimal("15.50"),
        )

        self.client = DjangoClient()
        self.client.login(username="testadmin", password="testpass123")

    def test_get_commission_rate_success(self):
        url = reverse("insurers:api_commission_rate")
        response = self.client.get(
            url,
            {
                "insurer_id": self.insurer.id,
                "insurance_type_id": self.insurance_type.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data["success"])
        self.assertEqual(data["commission_rate_id"], self.commission_rate.id)
        self.assertEqual(data["kv_percent"], "15.50")
        self.assertIn("display_name", data)

    def test_get_commission_rate_not_found(self):
        other_type = InsuranceType.objects.create(name="Спецтехника")

        url = reverse("insurers:api_commission_rate")
        response = self.client.get(
            url, {"insurer_id": self.insurer.id, "insurance_type_id": other_type.id}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_get_commission_rate_missing_params(self):
        url = reverse("insurers:api_commission_rate")
        response = self.client.get(url, {"insurer_id": self.insurer.id})

        self.assertEqual(response.status_code, 400)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_get_commission_rate_requires_staff(self):
        regular_user = User.objects.create_user(
            username="regular", password="testpass123", is_staff=False
        )

        client = DjangoClient()
        client.login(username="regular", password="testpass123")

        url = reverse("insurers:api_commission_rate")
        response = client.get(
            url,
            {
                "insurer_id": self.insurer.id,
                "insurance_type_id": self.insurance_type.id,
            },
        )

        self.assertIn(response.status_code, [302, 403])

    def test_get_commission_rate_handles_unexpected_error(self):
        url = reverse("insurers:api_commission_rate")
        with patch(
            "apps.insurers.views.CommissionRate.objects.get",
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.get(
                url,
                {
                    "insurer_id": self.insurer.id,
                    "insurance_type_id": self.insurance_type.id,
                },
            )

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Ошибка", data["error"])


class InsurerListViewTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()
        self.user = User.objects.create_user(
            username="list_user", password="testpass123"
        )
        self.client.login(username="list_user", password="testpass123")

    def test_list_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("insurers:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_list_search_filters_queryset(self):
        Insurer.objects.create(insurer_name="Другая страховая")
        response = self.client.get(reverse("insurers:list"), {"search": "Тестовая"})
        self.assertEqual(response.status_code, 200)

        insurers = list(response.context["insurers"])
        self.assertEqual(len(insurers), 1)
        self.assertEqual(insurers[0].id, self.insurer.id)

    def test_list_attaches_statistics_for_each_insurer(self):
        response = self.client.get(reverse("insurers:list"))
        self.assertEqual(response.status_code, 200)

        insurers = list(response.context["insurers"])
        target = [ins for ins in insurers if ins.id == self.insurer.id][0]

        self.assertEqual(target.stats["total_policies"], 3)
        self.assertEqual(target.stats["active_policies"], 2)
        self.assertEqual(target.stats["broker_participation"], 2)
        self.assertEqual(target.stats["broker_percentage"], 100.0)

        type_distribution = target.stats["type_distribution"]
        self.assertEqual(len(type_distribution), 1)
        self.assertEqual(type_distribution[0]["name"], "КАСКО")
        self.assertEqual(type_distribution[0]["count"], 2)
        self.assertEqual(type_distribution[0]["percentage"], 100.0)
        self.assertTrue(type_distribution[0]["color"].startswith("#"))


class BranchListViewTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()
        self.user = User.objects.create_user(
            username="branch_list_user", password="testpass123"
        )
        self.client.login(username="branch_list_user", password="testpass123")

    def test_list_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("insurers:branches_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_list_search_filters_queryset(self):
        Branch.objects.create(branch_name="Дальний филиал")
        response = self.client.get(
            reverse("insurers:branches_list"), {"search": "Филиал А"}
        )
        self.assertEqual(response.status_code, 200)

        branches = list(response.context["branches"])
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0].id, self.branch_a.id)

    def test_list_attaches_statistics_for_each_branch(self):
        response = self.client.get(reverse("insurers:branches_list"))
        self.assertEqual(response.status_code, 200)

        branches = {branch.id: branch for branch in response.context["branches"]}
        branch_a_stats = branches[self.branch_a.id].stats
        branch_b_stats = branches[self.branch_b.id].stats

        self.assertEqual(branch_a_stats["total_policies"], 2)
        self.assertEqual(branch_a_stats["active_policies"], 1)
        self.assertEqual(branch_a_stats["broker_participation"], 1)
        self.assertEqual(branch_a_stats["broker_percentage"], 100.0)
        self.assertEqual(branch_a_stats["type_distribution"][0]["name"], "КАСКО")
        self.assertEqual(branch_a_stats["type_distribution"][0]["count"], 1)

        self.assertEqual(branch_b_stats["total_policies"], 1)
        self.assertEqual(branch_b_stats["active_policies"], 1)


class InsurerStatisticsServiceTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()

    def test_parse_filters_defaults_and_swaps_dates(self):
        filters = InsurerStatisticsService.parse_filters(
            selected_branch_id="not-int",
            selected_insurance_type_id="",
            stats_scope="current",
            policy_scope="invalid",
            metric="invalid",
            date_from="2026-12-31",
            date_to="2026-01-01",
        )

        self.assertIsNone(filters.selected_branch_id)
        self.assertEqual(filters.stats_scope, "all")
        self.assertEqual(filters.policy_scope, "active")
        self.assertEqual(filters.metric, "premium")
        self.assertEqual(filters.date_from, date(2026, 1, 1))
        self.assertEqual(filters.date_to, date(2026, 12, 31))

    def test_calculate_with_count_metric(self):
        service = InsurerStatisticsService(self.insurer)
        filters = InsurerStatisticsService.parse_filters(
            selected_branch_id=None,
            selected_insurance_type_id=None,
            stats_scope="all",
            policy_scope="all",
            metric="count",
            date_from=None,
            date_to=None,
        )

        statistics = service.calculate(filters)

        self.assertEqual(statistics["total_policies"], 3)
        self.assertEqual(statistics["active_policies"], 2)
        self.assertEqual(statistics["inactive_policies"], 1)
        self.assertEqual(statistics["scoped_policies"], 3)

        self.assertEqual(statistics["branch_distribution"][0]["id"], self.branch_a.id)
        self.assertEqual(statistics["branch_distribution"][0]["count"], 2)
        self.assertEqual(statistics["branch_distribution"][1]["id"], self.branch_b.id)
        self.assertEqual(statistics["branch_distribution"][1]["count"], 1)

        self.assertEqual(
            statistics["branch_chart_data"]["values"],
            [2.0, 1.0],
        )

    def test_calculate_with_premium_metric_in_current_branch(self):
        service = InsurerStatisticsService(self.insurer)
        filters = InsurerStatisticsService.parse_filters(
            selected_branch_id=str(self.branch_a.id),
            selected_insurance_type_id=None,
            stats_scope="current",
            policy_scope="all",
            metric="premium",
            date_from=None,
            date_to=None,
        )

        statistics = service.calculate(filters)

        self.assertEqual(statistics["total_policies"], 2)
        self.assertEqual(statistics["active_policies"], 1)
        self.assertEqual(statistics["inactive_policies"], 1)
        self.assertEqual(statistics["total_premium"], Decimal("5000"))

        self.assertEqual(len(statistics["branch_distribution"]), 1)
        self.assertEqual(statistics["branch_distribution"][0]["id"], self.branch_a.id)
        self.assertEqual(
            statistics["branch_distribution"][0]["metric_value_float"], 5000.0
        )
        self.assertEqual(statistics["type_distribution"][0]["id"], self.type_osago.id)
        self.assertEqual(statistics["type_distribution"][0]["count"], 1)
        self.assertEqual(statistics["broker_participation"], 1)
        self.assertEqual(statistics["broker_percentage"], 50.0)

    def test_active_policy_scope_affects_scoped_values(self):
        service = InsurerStatisticsService(self.insurer)
        filters = InsurerStatisticsService.parse_filters(
            selected_branch_id=None,
            selected_insurance_type_id=None,
            stats_scope="all",
            policy_scope="active",
            metric="count",
            date_from=None,
            date_to=None,
        )

        statistics = service.calculate(filters)

        self.assertEqual(statistics["total_policies"], 3)
        self.assertEqual(statistics["scoped_policies"], 2)
        self.assertEqual(statistics["total_premium"], Decimal("10000"))
        self.assertEqual(statistics["broker_participation"], 2)
        self.assertEqual(statistics["broker_percentage"], 100.0)


class BranchStatisticsServiceTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()
        self.second_insurer = Insurer.objects.create(insurer_name="СК Дополнительная")
        self.policy_a3 = self._create_policy(
            policy_number="POL-004",
            branch=self.branch_a,
            insurance_type=self.type_casco,
            premium=Decimal("2000.00"),
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
            policy_active=True,
            broker_participation=True,
            insurer=self.second_insurer,
        )

    def test_parse_filters_defaults_and_swaps_dates(self):
        filters = BranchStatisticsService.parse_filters(
            selected_insurer_id="not-int",
            selected_insurance_type_id="",
            stats_scope="current",
            policy_scope="invalid",
            metric="invalid",
            date_from="2026-12-31",
            date_to="2026-01-01",
        )

        self.assertIsNone(filters.selected_insurer_id)
        self.assertEqual(filters.stats_scope, "all")
        self.assertEqual(filters.policy_scope, "active")
        self.assertEqual(filters.metric, "premium")
        self.assertEqual(filters.date_from, date(2026, 1, 1))
        self.assertEqual(filters.date_to, date(2026, 12, 31))

    def test_calculate_with_count_metric(self):
        service = BranchStatisticsService(self.branch_a)
        filters = BranchStatisticsService.parse_filters(
            selected_insurer_id=None,
            selected_insurance_type_id=None,
            stats_scope="all",
            policy_scope="all",
            metric="count",
            date_from=None,
            date_to=None,
        )

        statistics = service.calculate(filters)

        self.assertEqual(statistics["total_policies"], 3)
        self.assertEqual(statistics["active_policies"], 2)
        self.assertEqual(statistics["inactive_policies"], 1)
        self.assertEqual(statistics["scoped_policies"], 3)

        self.assertEqual(statistics["insurer_distribution"][0]["id"], self.insurer.id)
        self.assertEqual(statistics["insurer_distribution"][0]["count"], 2)
        self.assertEqual(
            statistics["insurer_distribution"][1]["id"], self.second_insurer.id
        )
        self.assertEqual(statistics["insurer_distribution"][1]["count"], 1)
        self.assertEqual(
            statistics["insurer_chart_data"]["values"],
            [2.0, 1.0],
        )

    def test_calculate_with_premium_metric_for_selected_insurer(self):
        service = BranchStatisticsService(self.branch_a)
        filters = BranchStatisticsService.parse_filters(
            selected_insurer_id=str(self.second_insurer.id),
            selected_insurance_type_id=None,
            stats_scope="current",
            policy_scope="all",
            metric="premium",
            date_from=None,
            date_to=None,
        )

        statistics = service.calculate(filters)

        self.assertEqual(statistics["total_policies"], 1)
        self.assertEqual(statistics["active_policies"], 1)
        self.assertEqual(statistics["inactive_policies"], 0)
        self.assertEqual(statistics["total_premium"], Decimal("2000"))
        self.assertEqual(len(statistics["insurer_distribution"]), 1)
        self.assertEqual(
            statistics["insurer_distribution"][0]["id"], self.second_insurer.id
        )
        self.assertEqual(
            statistics["insurer_distribution"][0]["metric_value_float"], 2000.0
        )
        self.assertEqual(statistics["broker_participation"], 1)
        self.assertEqual(statistics["broker_percentage"], 100.0)

    def test_active_policy_scope_affects_scoped_values(self):
        service = BranchStatisticsService(self.branch_a)
        filters = BranchStatisticsService.parse_filters(
            selected_insurer_id=None,
            selected_insurance_type_id=None,
            stats_scope="all",
            policy_scope="active",
            metric="count",
            date_from=None,
            date_to=None,
        )

        statistics = service.calculate(filters)

        self.assertEqual(statistics["total_policies"], 3)
        self.assertEqual(statistics["scoped_policies"], 2)
        self.assertEqual(statistics["total_premium"], Decimal("3000"))
        self.assertEqual(statistics["broker_participation"], 2)
        self.assertEqual(statistics["broker_percentage"], 100.0)


class InsurerDetailViewTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()
        self.user = User.objects.create_user(
            username="insurer_user", password="testpass123"
        )
        self.client.login(username="insurer_user", password="testpass123")

    def test_detail_applies_branch_and_type_filters_to_table_and_stats(self):
        response = self.client.get(
            reverse("insurers:detail", args=[self.insurer.id]),
            {
                "branch": str(self.branch_a.id),
                "insurance_type": str(self.type_osago.id),
                "stats_scope": "current",
                "policy_scope": "all",
                "metric": "premium",
            },
        )

        self.assertEqual(response.status_code, 200)

        policies = list(response.context["policies"])
        self.assertEqual(len(policies), 1)
        self.assertEqual(policies[0].id, self.policy_a2.id)
        self.assertEqual(response.context["policies_count"], 1)

        self.assertEqual(response.context["selected_branch_id"], self.branch_a.id)
        self.assertEqual(
            response.context["selected_insurance_type_id"], self.type_osago.id
        )
        self.assertEqual(response.context["stats_scope"], "current")
        self.assertEqual(response.context["policy_scope"], "all")
        self.assertEqual(response.context["metric"], "premium")

        statistics = response.context["statistics"]
        self.assertEqual(statistics["total_policies"], 1)
        self.assertEqual(statistics["scoped_policies"], 1)
        self.assertEqual(statistics["total_premium"], Decimal("4000"))
        self.assertEqual(statistics["branch_distribution"][0]["id"], self.branch_a.id)

    def test_detail_invalid_filters_fallback_to_defaults(self):
        response = self.client.get(
            reverse("insurers:detail", args=[self.insurer.id]),
            {
                "branch": "abc",
                "insurance_type": "xyz",
                "stats_scope": "current",
                "policy_scope": "wrong",
                "metric": "wrong",
                "date_from": "2026-12-31",
                "date_to": "2026-01-01",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertIsNone(response.context["selected_branch_id"])
        self.assertIsNone(response.context["selected_insurance_type_id"])
        self.assertEqual(response.context["stats_scope"], "all")
        self.assertEqual(response.context["policy_scope"], "active")
        self.assertEqual(response.context["metric"], "premium")
        self.assertEqual(response.context["date_from"], date(2026, 1, 1))
        self.assertEqual(response.context["date_to"], date(2026, 12, 31))

        policies = list(response.context["policies"])
        self.assertEqual(len(policies), 3)

        statistics = response.context["statistics"]
        self.assertEqual(statistics["policy_scope"], "active")
        self.assertEqual(statistics["metric"], "premium")
        self.assertEqual(statistics["scoped_policies"], 2)


class BranchDetailViewTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()
        self.user = User.objects.create_user(
            username="branch_user", password="testpass123"
        )
        self.client.login(username="branch_user", password="testpass123")

        self.second_insurer = Insurer.objects.create(insurer_name="СК Дополнительная")
        self.policy_a3 = self._create_policy(
            policy_number="POL-004",
            branch=self.branch_a,
            insurance_type=self.type_casco,
            premium=Decimal("2000.00"),
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
            policy_active=True,
            broker_participation=True,
            insurer=self.second_insurer,
        )

        self.manager_ivan = LeasingManager.objects.create(
            name="Иванов",
            full_name="Иван Иванович Иванов",
            phone="+79990001122",
            email="ivanov@example.com",
        )
        self.manager_petr = LeasingManager.objects.create(
            name="Петров", full_name="Петр Петрович Петров"
        )
        self.policy_a1.leasing_manager = self.manager_ivan
        self.policy_a1.save(update_fields=["leasing_manager"])
        self.policy_a2.leasing_manager = self.manager_ivan
        self.policy_a2.save(update_fields=["leasing_manager"])
        self.policy_b1.leasing_manager = self.manager_ivan
        self.policy_b1.save(update_fields=["leasing_manager"])
        self.policy_a3.leasing_manager = self.manager_petr
        self.policy_a3.save(update_fields=["leasing_manager"])

    def test_detail_requires_authentication(self):
        self.client.logout()
        response = self.client.get(
            reverse("insurers:branch_detail", args=[self.branch_a.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_detail_applies_insurer_and_type_filters_to_table_and_stats(self):
        response = self.client.get(
            reverse("insurers:branch_detail", args=[self.branch_a.id]),
            {
                "insurer": str(self.second_insurer.id),
                "insurance_type": str(self.type_casco.id),
                "stats_scope": "current",
                "policy_scope": "all",
                "metric": "premium",
            },
        )

        self.assertEqual(response.status_code, 200)

        policies = list(response.context["policies"])
        self.assertEqual(len(policies), 1)
        self.assertEqual(policies[0].id, self.policy_a3.id)
        self.assertEqual(response.context["policies_count"], 1)

        self.assertEqual(
            response.context["selected_insurer_id"], self.second_insurer.id
        )
        self.assertEqual(
            response.context["selected_insurance_type_id"], self.type_casco.id
        )
        self.assertEqual(response.context["stats_scope"], "current")
        self.assertEqual(response.context["policy_scope"], "all")
        self.assertEqual(response.context["metric"], "premium")

        statistics = response.context["statistics"]
        self.assertEqual(statistics["total_policies"], 1)
        self.assertEqual(statistics["scoped_policies"], 1)
        self.assertEqual(statistics["total_premium"], Decimal("2000"))
        self.assertEqual(
            statistics["insurer_distribution"][0]["id"], self.second_insurer.id
        )

    def test_detail_invalid_filters_fallback_to_defaults(self):
        response = self.client.get(
            reverse("insurers:branch_detail", args=[self.branch_a.id]),
            {
                "insurer": "abc",
                "insurance_type": "xyz",
                "stats_scope": "current",
                "policy_scope": "wrong",
                "metric": "wrong",
                "date_from": "2026-12-31",
                "date_to": "2026-01-01",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertIsNone(response.context["selected_insurer_id"])
        self.assertIsNone(response.context["selected_insurance_type_id"])
        self.assertEqual(response.context["stats_scope"], "all")
        self.assertEqual(response.context["policy_scope"], "active")
        self.assertEqual(response.context["metric"], "premium")
        self.assertEqual(response.context["date_from"], date(2026, 1, 1))
        self.assertEqual(response.context["date_to"], date(2026, 12, 31))

        policies = list(response.context["policies"])
        self.assertEqual(len(policies), 3)

        statistics = response.context["statistics"]
        self.assertEqual(statistics["policy_scope"], "active")
        self.assertEqual(statistics["metric"], "premium")
        self.assertEqual(statistics["scoped_policies"], 2)

    def test_detail_returns_branch_specific_managers(self):
        response = self.client.get(
            reverse("insurers:branch_detail", args=[self.branch_a.id])
        )
        self.assertEqual(response.status_code, 200)

        managers = {manager.id: manager for manager in response.context["managers"]}
        self.assertEqual(len(managers), 2)
        self.assertEqual(managers[self.manager_ivan.id].total_policies, 2)
        self.assertEqual(managers[self.manager_ivan.id].active_policies, 1)
        self.assertEqual(managers[self.manager_petr.id].total_policies, 1)
        self.assertEqual(managers[self.manager_petr.id].active_policies, 1)

    def test_policy_detail_contains_link_to_branch_card(self):
        response = self.client.get(reverse("policies:detail", args=[self.policy_a1.id]))
        self.assertEqual(response.status_code, 200)
        branch_url = reverse("insurers:branch_detail", args=[self.branch_a.id])
        self.assertContains(response, branch_url)
        self.assertContains(response, self.branch_a.branch_name)


class EcosystemHubViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ecosystem_user", password="testpass123"
        )
        self.client.login(username="ecosystem_user", password="testpass123")

    def test_ecosystem_hub_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("insurers:ecosystem"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_ecosystem_hub_renders_links_and_counts(self):
        Branch.objects.create(branch_name="Тестовый филиал")
        LeasingManager.objects.create(name="Смирнов")
        Insurer.objects.create(insurer_name="Тестовый страховщик")
        LeasingClient.objects.create(
            client_name="Тестовый лизингополучатель", client_inn="7700000001"
        )

        response = self.client.get(reverse("insurers:ecosystem"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("insurers:branches_list"))
        self.assertContains(response, reverse("insurers:managers_list"))
        self.assertContains(response, reverse("clients:list"))
        self.assertContains(response, reverse("insurers:list"))
        self.assertEqual(response.context["branch_count"], Branch.objects.count())
        self.assertEqual(
            response.context["manager_count"], LeasingManager.objects.count()
        )
        self.assertEqual(
            response.context["client_count"], LeasingClient.objects.count()
        )
        self.assertEqual(response.context["insurer_count"], Insurer.objects.count())


class LeasingManagerViewsTest(InsurerStatisticsTestDataMixin, TestCase):
    def setUp(self):
        self.setUp_statistics_data()
        self.user = User.objects.create_user(
            username="manager_user", password="testpass123"
        )
        self.client.login(username="manager_user", password="testpass123")

        self.manager_ivan = LeasingManager.objects.create(
            name="Иванов",
            full_name="Иван Иванович Иванов",
            phone="+79990001122",
            email="ivanov@example.com",
        )
        self.manager_petr = LeasingManager.objects.create(
            name="Петров", full_name="Петр Петрович Петров"
        )
        self.manager_empty = LeasingManager.objects.create(name="Сидоров")

        self.policy_a1.leasing_manager = self.manager_ivan
        self.policy_a1.save(update_fields=["leasing_manager"])
        self.policy_b1.leasing_manager = self.manager_ivan
        self.policy_b1.save(update_fields=["leasing_manager"])
        self.policy_a2.leasing_manager = self.manager_petr
        self.policy_a2.save(update_fields=["leasing_manager"])

    def test_manager_list_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("insurers:managers_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_manager_list_search_filters_queryset(self):
        response = self.client.get(
            reverse("insurers:managers_list"), {"search": "Иванович"}
        )
        self.assertEqual(response.status_code, 200)
        managers = list(response.context["managers"])
        self.assertEqual(len(managers), 1)
        self.assertEqual(managers[0].id, self.manager_ivan.id)

    def test_manager_list_attaches_policy_stats(self):
        response = self.client.get(reverse("insurers:managers_list"))
        self.assertEqual(response.status_code, 200)
        managers = {manager.id: manager for manager in response.context["managers"]}

        self.assertEqual(managers[self.manager_ivan.id].total_policies, 2)
        self.assertEqual(managers[self.manager_ivan.id].active_policies, 2)
        self.assertEqual(managers[self.manager_petr.id].total_policies, 1)
        self.assertEqual(managers[self.manager_petr.id].active_policies, 0)
        self.assertEqual(managers[self.manager_empty.id].total_policies, 0)
        self.assertEqual(managers[self.manager_empty.id].active_policies, 0)

    def test_manager_detail_shows_only_related_policies(self):
        response = self.client.get(
            reverse("insurers:manager_detail", args=[self.manager_ivan.id])
        )
        self.assertEqual(response.status_code, 200)

        policies = list(response.context["policies"])
        self.assertEqual(len(policies), 2)
        self.assertSetEqual(
            {policy.id for policy in policies},
            {self.policy_a1.id, self.policy_b1.id},
        )
        self.assertEqual(response.context["policies_count"], 2)

        overview = response.context["manager_overview"]
        self.assertEqual(overview["total_policies"], 2)
        self.assertEqual(overview["active_policies"], 2)
        self.assertEqual(overview["terminated_policies"], 0)
        self.assertEqual(overview["nearest_end_date"], self.policy_a1.end_date)

    def test_manager_detail_ignores_branch_query_param(self):
        response = self.client.get(
            reverse("insurers:manager_detail", args=[self.manager_ivan.id]),
            {"branch": str(self.branch_b.id)},
        )
        self.assertEqual(response.status_code, 200)

        policies = list(response.context["policies"])
        self.assertEqual(len(policies), 2)
        self.assertSetEqual(
            {policy.id for policy in policies},
            {self.policy_a1.id, self.policy_b1.id},
        )

    def test_manager_detail_highlights_no_broker_policy_rows(self):
        self.policy_a1.broker_participation = False
        self.policy_a1.save(update_fields=["broker_participation"])

        response = self.client.get(
            reverse("insurers:manager_detail", args=[self.manager_ivan.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "row--nobroker")
        self.assertContains(response, "Без брокера")

    def test_policy_detail_contains_link_to_manager_card(self):
        response = self.client.get(reverse("policies:detail", args=[self.policy_a1.id]))
        self.assertEqual(response.status_code, 200)
        manager_url = reverse("insurers:manager_detail", args=[self.manager_ivan.id])
        self.assertContains(response, manager_url)
        self.assertContains(response, self.manager_ivan.name)


class InsurerTemplateTagsTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_update_query_adds_updates_and_removes_params(self):
        request = self.factory.get("/insurers/1/?branch=2&metric=count")
        query = update_query({"request": request}, branch="", metric="premium", page=3)
        self.assertEqual(query, "metric=premium&page=3")

    def test_update_query_without_request_returns_empty_string(self):
        self.assertEqual(update_query({}, branch=1), "")

    def test_inclusion_tags_resolve_size_map(self):
        insurer = Insurer.objects.create(insurer_name="Tag Insurance")
        branch = Branch.objects.create(branch_name="Tag Branch")
        insurance_type = InsuranceType.objects.create(name="Tag Type")

        insurer_context = insurer_logo(insurer, size="small")
        branch_context = branch_logo(branch, size="large")
        type_context = insurance_type_icon(insurance_type, size="unknown")

        self.assertEqual(insurer_context["size"], "24px")
        self.assertEqual(branch_context["size"], "48px")
        self.assertEqual(type_context["size"], "32px")

    def test_ru_pluralize_covers_all_branches(self):
        self.assertEqual(ru_pluralize(1, "полис,полиса,полисов"), "полис")
        self.assertEqual(ru_pluralize(2, "полис,полиса,полисов"), "полиса")
        self.assertEqual(ru_pluralize(5, "полис,полиса,полисов"), "полисов")
        self.assertEqual(ru_pluralize(3, "полис"), "полис")
        self.assertEqual(ru_pluralize("bad", "полис,полиса,полисов"), "")


class InsurerModelStringRepresentationTest(TestCase):
    def test_info_tag_and_leasing_manager_str(self):
        tag = InfoTag.objects.create(name="VIP")
        manager = LeasingManager.objects.create(name="Иванов")
        self.assertEqual(str(tag), "VIP")
        self.assertEqual(str(manager), "Иванов")
