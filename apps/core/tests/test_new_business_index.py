"""
Unit tests for the New Business Development Index.

Covers:
- Pure calculation functions (_nb_safe_ratio, _nb_momentum, _nb_score)
- Edge cases: zero denominators, all-zero data, clipping boundaries
- _build_new_business_index: data present / no data fallback
- Context key presence in get_dashboard_context
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.clients.models import Client
from apps.core.services.dashboard_v2_service import (
    DECIMAL_ZERO,
    DashboardV2Service,
    _nb_interpretation,
    _nb_momentum,
    _nb_safe_ratio,
    _nb_score,
)
from apps.insurers.models import Branch, CommissionRate, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy


# ─── Pure-function unit tests ────────────────────────────────────────────────


class NbSafeRatioTests(TestCase):
    def test_normal_division(self):
        self.assertEqual(_nb_safe_ratio(Decimal("10"), Decimal("5")), Decimal("2"))

    def test_zero_denominator_positive_numerator_returns_upper_clip(self):
        result = _nb_safe_ratio(Decimal("5"), DECIMAL_ZERO)
        self.assertEqual(result, Decimal("1.5"))

    def test_zero_denominator_zero_numerator_returns_plateau(self):
        result = _nb_safe_ratio(DECIMAL_ZERO, DECIMAL_ZERO)
        self.assertEqual(result, Decimal("1.0"))


class NbMomentumTests(TestCase):
    def test_plateau_equal_rates(self):
        # Same daily rate across all windows → momentum = 1.0
        result = _nb_momentum(Decimal("10"), Decimal("10"), Decimal("10"))
        self.assertEqual(result, Decimal("1.0"))

    def test_growth_higher_recent_rate(self):
        # x30d > x60d and x30d > x90d → momentum > 1
        result = _nb_momentum(Decimal("20"), Decimal("10"), Decimal("10"))
        self.assertGreater(result, Decimal("1.0"))

    def test_decline_lower_recent_rate(self):
        # x30d < x60d and x30d < x90d → momentum < 1
        result = _nb_momentum(Decimal("5"), Decimal("10"), Decimal("10"))
        self.assertLess(result, Decimal("1.0"))

    def test_weights_60_heavier_than_90(self):
        # 60d denominator dominates (weight 0.6): set x60d high, x90d low
        # r60 = 10/20 = 0.5, r90 = 10/5 = 2.0
        # M = 0.6*0.5 + 0.4*2.0 = 0.3 + 0.8 = 1.1
        result = _nb_momentum(Decimal("10"), Decimal("20"), Decimal("5"))
        self.assertEqual(result, Decimal("1.1"))

    def test_zero_denominators_both_positive_numerator(self):
        # Both 60d and 90d are zero but 30d > 0 → both ratios clip to 1.5
        # M = 0.6*1.5 + 0.4*1.5 = 1.5
        result = _nb_momentum(Decimal("5"), DECIMAL_ZERO, DECIMAL_ZERO)
        self.assertEqual(result, Decimal("1.5"))


class NbScoreTests(TestCase):
    def test_plateau_gives_50(self):
        # Equal totals scaled correctly → daily rates equal → momentum=1 → score=50
        result = _nb_score(Decimal("30"), Decimal("60"), Decimal("90"))
        self.assertEqual(result, Decimal("50.0"))

    def test_max_growth_clipped_to_100(self):
        # Huge 30d value, zero older windows → clips to 1.5 → score=100
        result = _nb_score(Decimal("9999"), DECIMAL_ZERO, DECIMAL_ZERO)
        self.assertEqual(result, Decimal("100.0"))

    def test_max_decline_clipped_to_0(self):
        # Zero 30d, large older windows → momentum clips to 0.5 → score=0
        result = _nb_score(DECIMAL_ZERO, Decimal("6000"), Decimal("9000"))
        self.assertEqual(result, Decimal("0.0"))

    def test_score_in_range(self):
        for x30, x60, x90 in [
            (Decimal("10"), Decimal("30"), Decimal("60")),
            (Decimal("50"), Decimal("30"), Decimal("60")),
            (Decimal("1"), Decimal("1"), Decimal("1")),
        ]:
            score = _nb_score(x30, x60, x90)
            self.assertGreaterEqual(score, DECIMAL_ZERO)
            self.assertLessEqual(score, Decimal("100"))


class NbInterpretationTests(TestCase):
    def test_boundaries(self):
        cases = [
            (Decimal("0"), "Снижение"),
            (Decimal("34.9"), "Снижение"),
            (Decimal("35"), "Слабая динамика"),
            (Decimal("44.9"), "Слабая динамика"),
            (Decimal("45"), "Плато"),
            (Decimal("54.9"), "Плато"),
            (Decimal("55"), "Умеренный рост"),
            (Decimal("69.9"), "Умеренный рост"),
            (Decimal("70"), "Сильный рост"),
            (Decimal("84.9"), "Сильный рост"),
            (Decimal("85"), "Очень сильный рост"),
            (Decimal("100"), "Очень сильный рост"),
        ]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(_nb_interpretation(score), expected)


# ─── Integration tests with database ─────────────────────────────────────────


class NbIndexBuildTests(TestCase):
    """Tests for _build_new_business_index against a real test DB."""

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.insurer = Insurer.objects.create(insurer_name="СК НБИ")
        cls.branch = Branch.objects.create(branch_name="НБИ Филиал")
        cls.ins_type = InsuranceType.objects.create(name="НБИ Тип")
        cls.leasing_client = Client.objects.create(
            client_name="НБИ Клиент", client_inn="9876543210"
        )
        cls.commission_rate = CommissionRate.objects.create(
            insurer=cls.insurer,
            insurance_type=cls.ins_type,
            kv_percent=Decimal("10.00"),
        )

    def _make_policy(self, start_offset_days, premium=Decimal("1000")):
        p = Policy.objects.create(
            policy_number=f"NBI-{start_offset_days}-{premium}",
            client=self.leasing_client,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.ins_type,
            property_description="Тест",
            start_date=self.today - timedelta(days=start_offset_days),
            end_date=self.today + timedelta(days=365),
            franchise=Decimal("0"),
        )
        PaymentSchedule.objects.create(
            policy=p,
            year_number=1,
            installment_number=1,
            due_date=self.today + timedelta(days=30),
            amount=premium,
            insurance_sum=premium * 10,
            commission_rate=self.commission_rate,
            kv_rub=premium * Decimal("0.1"),
        )
        return p

    def test_no_data_returns_has_data_false(self):
        result = DashboardV2Service()._build_new_business_index(
            policies_qs=Policy.objects.none(),
            today=self.today,
        )
        self.assertFalse(result["has_data"])
        self.assertIsNone(result["score"])
        self.assertEqual(result["interpretation"], "Недостаточно данных")
        self.assertEqual(result["components"], [])

    def test_plateau_equal_distribution_across_windows(self):
        # Distribute policies evenly so daily rates are equal → score ≈ 50
        # 30d window: 1 policy; 60d window: 2 total (→ 1 extra in 31–60d);
        # 90d window: 3 total (→ 1 extra in 61–90d)
        # daily: 1/30, 2/60=1/30, 3/90=1/30 → all equal → momentum=1 → score=50
        self._make_policy(start_offset_days=15)  # in 30d window
        self._make_policy(start_offset_days=45)  # in 60d window, not 30d
        self._make_policy(start_offset_days=75)  # in 90d window, not 60d

        result = DashboardV2Service()._build_new_business_index(
            policies_qs=Policy.objects.filter(policy_number__startswith="NBI-"),
            today=self.today,
        )
        self.assertTrue(result["has_data"])
        self.assertEqual(len(result["components"]), 4)
        # All scores should be 50 (plateau)
        for comp in result["components"]:
            self.assertEqual(comp["score"], Decimal("50.0"), msg=comp["label"])
        self.assertEqual(result["score"], Decimal("50.0"))

    def test_growth_more_recent_policies(self):
        # More policies in the recent 30d window → momentum > 1 → score > 50
        for _ in range(6):
            self._make_policy(start_offset_days=10)  # all in 30d
        self._make_policy(start_offset_days=45)  # 1 in 31–60d
        self._make_policy(start_offset_days=75)  # 1 in 61–90d

        result = DashboardV2Service()._build_new_business_index(
            policies_qs=Policy.objects.filter(policy_number__startswith="NBI-"),
            today=self.today,
        )
        self.assertTrue(result["has_data"])
        self.assertGreater(result["score"], Decimal("50"))

    def test_context_key_present(self):
        self._make_policy(start_offset_days=10)
        context = DashboardV2Service().get_dashboard_context()
        self.assertIn("dashboard_v2_nb_index", context)
        nb = context["dashboard_v2_nb_index"]
        self.assertIn("has_data", nb)
        self.assertIn("score", nb)
        self.assertIn("components", nb)
        self.assertIn("windows", nb)

    def test_windows_contain_expected_keys(self):
        self._make_policy(start_offset_days=10)
        result = DashboardV2Service()._build_new_business_index(
            policies_qs=Policy.objects.filter(policy_number__startswith="NBI-"),
            today=self.today,
        )
        for window in ("30", "60", "90"):
            self.assertIn(window, result["windows"])
            w = result["windows"][window]
            self.assertIn("count", w)
            self.assertIn("premium", w)
            self.assertIn("ins_sum", w)
            self.assertIn("commission", w)
