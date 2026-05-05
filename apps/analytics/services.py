"""
Analytics services for calculating business metrics and analytics.
This module contains the core business logic for analytics calculations.
"""

from decimal import Decimal
from datetime import date, datetime, timedelta
import calendar
from collections import defaultdict
from typing import Optional, Dict, Any
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce


def _policy_premium_subquery():
    """
    Subquery для получения суммы платежей одного полиса.

    Используется в .annotate(premium=Subquery(_policy_premium_subquery()))
    или внутри Sum(Subquery(...)) для агрегации по группам полисов.

    Subquery вместо Sum("payment_schedule__amount") нужен чтобы избежать
    double-counting при наличии других JOIN'ов (info_tags и т.п.).
    """
    from apps.policies.models import PaymentSchedule

    return (
        PaymentSchedule.objects.filter(policy=OuterRef("pk"))
        .values("policy")
        .annotate(total=Sum("amount"))
        .values("total")
    )


def _policy_insurance_sum_subquery_for_payment():
    """
    Subquery для получения одной страховой суммы полиса.

    Для аналитики страховая сумма договора считается как Max(insurance_sum)
    по всему графику платежей договора, чтобы многолетние договоры не
    умножались на количество лет или взносов.
    """
    from apps.policies.models import PaymentSchedule

    return (
        PaymentSchedule.objects.filter(policy_id=OuterRef("policy_id"))
        .values("policy_id")
        .annotate(total=Max("insurance_sum"))
        .values("total")
    )


from .chart_providers import ChartDataProvider


def sort_insurance_types(insurance_type_distribution: Dict[str, int]) -> Dict[str, int]:
    """
    Sort insurance types in the preferred order: КАСКО, Спецтехника, Имущество, Грузы, others.

    Args:
        insurance_type_distribution: Dictionary with insurance type names as keys and counts as values

    Returns:
        Sorted dictionary with insurance types in the preferred order
    """
    # Define the preferred order
    preferred_order = ["КАСКО", "Спецтехника", "Имущество", "Грузы"]

    sorted_distribution = {}

    # First, add items in the preferred order
    for insurance_type in preferred_order:
        # Look for exact match or case-insensitive match
        for key, value in insurance_type_distribution.items():
            if key and insurance_type.lower() in key.lower():
                sorted_distribution[key] = value
                break

    # Then add remaining items alphabetically
    remaining_items = {
        k: v
        for k, v in insurance_type_distribution.items()
        if k not in sorted_distribution
    }

    # Sort remaining items alphabetically
    for key in sorted(remaining_items.keys()):
        sorted_distribution[key] = remaining_items[key]

    return sorted_distribution


class MetricsCalculator:
    """
    Calculator for basic business metrics.
    Handles calculations for premium volume, commission revenue, insurance sum,
    policy count, and average commission rates.
    """

    def calculate_premium_volume(
        self, queryset: QuerySet, date_range: Optional[Dict[str, date]] = None
    ) -> Decimal:
        """
        Calculate total premium volume from payment schedule.

        Args:
            queryset: QuerySet of PaymentSchedule objects
            date_range: Optional dict with 'start' and 'end' date keys for filtering

        Returns:
            Total premium volume as Decimal
        """
        if date_range:
            if "start" in date_range and date_range["start"]:
                queryset = queryset.filter(due_date__gte=date_range["start"])
            if "end" in date_range and date_range["end"]:
                queryset = queryset.filter(due_date__lte=date_range["end"])

        result = queryset.aggregate(total=Coalesce(Sum("amount"), Decimal("0")))
        return result["total"]

    def calculate_commission_revenue(
        self, queryset: QuerySet, date_range: Optional[Dict[str, date]] = None
    ) -> Decimal:
        """
        Calculate total commission revenue from payment schedule.

        Args:
            queryset: QuerySet of PaymentSchedule objects
            date_range: Optional dict with 'start' and 'end' date keys for filtering

        Returns:
            Total commission revenue as Decimal
        """
        if date_range:
            if "start" in date_range and date_range["start"]:
                queryset = queryset.filter(due_date__gte=date_range["start"])
            if "end" in date_range and date_range["end"]:
                queryset = queryset.filter(due_date__lte=date_range["end"])

        result = queryset.aggregate(total=Coalesce(Sum("kv_rub"), Decimal("0")))
        return result["total"]

    def calculate_insurance_sum(
        self, queryset: QuerySet, date_range: Optional[Dict[str, date]] = None
    ) -> Decimal:
        """
        Calculate total insurance sum from payment schedule.

        Each policy contributes only once, using the maximum insurance_sum
        from the full payment schedule of that policy.

        Args:
            queryset: QuerySet of PaymentSchedule objects
            date_range: Optional dict with 'start' and 'end' date keys for filtering

        Returns:
            Total insurance sum as Decimal
        """
        if date_range:
            if "start" in date_range and date_range["start"]:
                queryset = queryset.filter(due_date__gte=date_range["start"])
            if "end" in date_range and date_range["end"]:
                queryset = queryset.filter(due_date__lte=date_range["end"])

        policy_rows = (
            queryset.order_by()
            .values("policy_id")
            .distinct()
            .annotate(
                policy_insurance_sum=Coalesce(
                    Subquery(
                        _policy_insurance_sum_subquery_for_payment(),
                        output_field=DecimalField(max_digits=15, decimal_places=2),
                    ),
                    Decimal("0"),
                )
            )
        )
        return sum(
            (row.get("policy_insurance_sum") or Decimal("0") for row in policy_rows),
            Decimal("0"),
        )

    def calculate_policy_count(
        self, queryset: QuerySet, date_range: Optional[Dict[str, date]] = None
    ) -> int:
        """
        Calculate count of unique policies from payment schedule or policy queryset.

        Args:
            queryset: QuerySet of PaymentSchedule or Policy objects
            date_range: Optional dict with 'start' and 'end' date keys for filtering

        Returns:
            Count of unique policies as int
        """
        # Check if this is a PaymentSchedule queryset or Policy queryset
        model_name = queryset.model._meta.model_name

        if model_name == "paymentschedule":
            if date_range:
                if "start" in date_range and date_range["start"]:
                    queryset = queryset.filter(due_date__gte=date_range["start"])
                if "end" in date_range and date_range["end"]:
                    queryset = queryset.filter(due_date__lte=date_range["end"])

            # Count distinct policies from payment schedule
            return queryset.values("policy").distinct().count()

        elif model_name == "policy":
            if date_range:
                if "start" in date_range and date_range["start"]:
                    queryset = queryset.filter(start_date__gte=date_range["start"])
                if "end" in date_range and date_range["end"]:
                    queryset = queryset.filter(start_date__lte=date_range["end"])

            # Count policies directly
            return queryset.count()

        else:
            raise ValueError(f"Unsupported model type: {model_name}")

    def calculate_average_commission_rate(self, queryset: QuerySet) -> Decimal:
        """
        Calculate average commission rate from payment schedule.
        Rate is calculated as (total commission / total premium) * 100.

        Args:
            queryset: QuerySet of PaymentSchedule objects

        Returns:
            Average commission rate as percentage (Decimal)
        """
        aggregates = queryset.aggregate(
            total_commission=Coalesce(Sum("kv_rub"), Decimal("0")),
            total_premium=Coalesce(Sum("amount"), Decimal("0")),
        )

        total_commission = aggregates["total_commission"]
        total_premium = aggregates["total_premium"]

        if total_premium > 0:
            return (total_commission / total_premium) * Decimal("100")

        return Decimal("0")


class AnalyticsFilter:
    """
    Filter system for analytics data.
    Handles filtering by dates, branches, insurers, insurance types, and clients.
    """

    def __init__(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        branch_ids: Optional[list] = None,
        insurer_ids: Optional[list] = None,
        insurance_type_ids: Optional[list] = None,
        client_ids: Optional[list] = None,
        policy_active: Optional[bool] = None,
        target_month: Optional[str] = None,
    ):
        self.date_from = date_from
        self.date_to = date_to
        self.branch_ids = branch_ids or []
        self.insurer_ids = insurer_ids or []
        self.insurance_type_ids = insurance_type_ids or []
        self.client_ids = client_ids or []
        self.policy_active = policy_active
        self.target_month = target_month

    def apply_to_policies(self, queryset: QuerySet) -> QuerySet:
        """
        Apply filters to a Policy queryset.

        Args:
            queryset: QuerySet of Policy objects

        Returns:
            Filtered QuerySet of Policy objects
        """
        # Date filtering based on policy start date
        if self.date_from:
            queryset = queryset.filter(start_date__gte=self.date_from)
        if self.date_to:
            queryset = queryset.filter(start_date__lte=self.date_to)

        # Branch filtering
        if self.branch_ids:
            queryset = queryset.filter(branch_id__in=self.branch_ids)

        # Insurer filtering
        if self.insurer_ids:
            queryset = queryset.filter(insurer_id__in=self.insurer_ids)

        # Insurance type filtering
        if self.insurance_type_ids:
            queryset = queryset.filter(insurance_type_id__in=self.insurance_type_ids)

        # Client filtering
        if self.client_ids:
            queryset = queryset.filter(client_id__in=self.client_ids)

        # Policy active filtering
        if self.policy_active is not None:
            queryset = queryset.filter(policy_active=self.policy_active)

        return queryset

    def apply_to_payments(self, queryset: QuerySet) -> QuerySet:
        """
        Apply filters to a PaymentSchedule queryset.

        Args:
            queryset: QuerySet of PaymentSchedule objects

        Returns:
            Filtered QuerySet of PaymentSchedule objects
        """
        # Date filtering based on payment due date
        if self.date_from:
            queryset = queryset.filter(due_date__gte=self.date_from)
        if self.date_to:
            queryset = queryset.filter(due_date__lte=self.date_to)

        # Branch filtering through policy relationship
        if self.branch_ids:
            queryset = queryset.filter(policy__branch_id__in=self.branch_ids)

        # Insurer filtering through policy relationship
        if self.insurer_ids:
            queryset = queryset.filter(policy__insurer_id__in=self.insurer_ids)

        # Insurance type filtering through policy relationship
        if self.insurance_type_ids:
            queryset = queryset.filter(
                policy__insurance_type_id__in=self.insurance_type_ids
            )

        # Client filtering through policy relationship
        if self.client_ids:
            queryset = queryset.filter(policy__client_id__in=self.client_ids)

        # Policy active filtering through policy relationship
        if self.policy_active is not None:
            queryset = queryset.filter(policy__policy_active=self.policy_active)

        return queryset

    def get_date_range_dict(self) -> Optional[Dict[str, date]]:
        """
        Get date range as dictionary for use with MetricsCalculator.

        Returns:
            Dictionary with 'start' and 'end' keys, or None if no dates set
        """
        if not self.date_from and not self.date_to:
            return None

        date_range = {}
        if self.date_from:
            date_range["start"] = self.date_from
        if self.date_to:
            date_range["end"] = self.date_to

        return date_range

    def has_filters(self) -> bool:
        """
        Check if any filters are applied.

        Returns:
            True if any filters are set, False otherwise
        """
        return bool(
            self.date_from
            or self.date_to
            or self.branch_ids
            or self.insurer_ids
            or self.insurance_type_ids
            or self.client_ids
            or self.policy_active is not None
            or self.target_month
        )


class AnalyticsService:
    """
    Main analytics service that integrates MetricsCalculator and AnalyticsFilter.
    Provides methods for getting all types of analytics with error handling and validation.
    """

    def __init__(self):
        self.calculator = MetricsCalculator()
        self.chart_provider = ChartDataProvider()

    @staticmethod
    def _build_policy_count_map(
        policies_qs: QuerySet, group_field: str
    ) -> Dict[int, int]:
        """Build a grouped policy count map by foreign key field."""
        rows = policies_qs.values(group_field).annotate(policy_count=Count("id"))
        counts: Dict[int, int] = {}
        for row in rows:
            group_id = row.get(group_field)
            if group_id is None:
                continue
            counts[int(group_id)] = int(row.get("policy_count") or 0)
        return counts

    @staticmethod
    def _build_payment_metrics_map(
        payments_qs: QuerySet,
        group_field: str,
        *,
        include_insurance_sum: bool = True,
    ) -> Dict[int, Dict[str, Decimal]]:
        """Build grouped premium/commission/insurance sum metrics by foreign key field."""
        rows = (
            payments_qs.order_by()
            .values(group_field)
            .annotate(
                premium_volume=Coalesce(Sum("amount"), Decimal("0")),
                commission_revenue=Coalesce(Sum("kv_rub"), Decimal("0")),
            )
        )
        metrics_map: Dict[int, Dict[str, Decimal]] = {}
        for row in rows:
            group_id = row.get(group_field)
            if group_id is None:
                continue
            metrics_map[int(group_id)] = {
                "premium_volume": row.get("premium_volume") or Decimal("0"),
                "commission_revenue": row.get("commission_revenue") or Decimal("0"),
                "insurance_sum": Decimal("0"),
            }

        if not include_insurance_sum:
            return metrics_map

        insurance_rows = (
            payments_qs.order_by()
            .values(group_field, "policy_id")
            .distinct()
            .annotate(
                policy_insurance_sum=Coalesce(
                    Subquery(
                        _policy_insurance_sum_subquery_for_payment(),
                        output_field=DecimalField(max_digits=15, decimal_places=2),
                    ),
                    Decimal("0"),
                )
            )
        )
        for row in insurance_rows:
            group_id = row.get(group_field)
            if group_id is None:
                continue
            metrics = metrics_map.setdefault(
                int(group_id),
                {
                    "premium_volume": Decimal("0"),
                    "commission_revenue": Decimal("0"),
                    "insurance_sum": Decimal("0"),
                },
            )
            metrics["insurance_sum"] += row.get("policy_insurance_sum") or Decimal("0")

        return metrics_map

    @staticmethod
    def _build_type_distribution_map(
        policies_qs: QuerySet, group_field: str
    ) -> Dict[int, Dict[str, int]]:
        """Build grouped insurance-type distribution map by foreign key field."""
        rows = (
            policies_qs.values(group_field, "insurance_type__name")
            .annotate(count=Count("id"))
            .order_by(group_field, "-count", "insurance_type__name")
        )
        distributions: Dict[int, Dict[str, int]] = defaultdict(dict)
        for row in rows:
            group_id = row.get(group_field)
            if group_id is None:
                continue
            type_name = row.get("insurance_type__name") or "Не указан вид"
            distributions[int(group_id)][type_name] = int(row.get("count") or 0)

        sorted_distributions: Dict[int, Dict[str, int]] = {}
        for group_id, type_distribution in distributions.items():
            sorted_distributions[group_id] = sort_insurance_types(type_distribution)
        return sorted_distributions

    @staticmethod
    def _add_months(base_date: date, months: int) -> date:
        """Add months to date preserving day as much as possible."""
        if months <= 0:
            return base_date

        month_index = base_date.month - 1 + months
        year = base_date.year + (month_index // 12)
        month = (month_index % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(base_date.day, max_day)
        return date(year, month, day)

    def _split_bridge_payments_by_month_boundary(self, payments_qs, current_date=None):
        """
        Split payments for the month-based bridge model:
        - closed months: use actual (paid) values
        - current/future months: use planned (scheduled) values
        """
        if current_date is None:
            current_date = datetime.now().date()

        current_month_start = date(current_date.year, current_date.month, 1)
        closed_months_qs = payments_qs.filter(due_date__lt=current_month_start)
        current_and_future_qs = payments_qs.filter(due_date__gte=current_month_start)
        closed_months_actual_qs = closed_months_qs.filter(paid_date__isnull=False)

        return closed_months_actual_qs, current_and_future_qs, current_month_start

    def get_dashboard_metrics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get dashboard metrics with key performance indicators.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing dashboard metrics
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)
                date_range = analytics_filter.get_date_range_dict()
            else:
                date_range = None

            (
                closed_months_actual_qs,
                current_and_future_qs,
                current_month_start,
            ) = self._split_bridge_payments_by_month_boundary(payments_qs)

            # Planned metrics (current and future months only)
            planned_premium_volume = self.calculator.calculate_premium_volume(
                current_and_future_qs
            )
            planned_commission_revenue = self.calculator.calculate_commission_revenue(
                current_and_future_qs
            )
            planned_insurance_sum = self.calculator.calculate_insurance_sum(
                current_and_future_qs
            )

            # Actual metrics (only paid payments from closed months)
            actual_premium_volume = self.calculator.calculate_premium_volume(
                closed_months_actual_qs
            )
            actual_commission_revenue = self.calculator.calculate_commission_revenue(
                closed_months_actual_qs
            )
            actual_insurance_sum = self.calculator.calculate_insurance_sum(
                closed_months_actual_qs
            )

            # Bridge totals: premium/commission are additive payment flows.
            # Insurance sum is a policy exposure, so a policy contributes once.
            bridge_premium_volume = actual_premium_volume + planned_premium_volume
            bridge_commission_revenue = (
                actual_commission_revenue + planned_commission_revenue
            )
            bridge_insurance_sum = self.calculator.calculate_insurance_sum(
                payments_qs.filter(
                    Q(due_date__lt=current_month_start, paid_date__isnull=False)
                    | Q(due_date__gte=current_month_start)
                )
            )

            total_policy_count = self.calculator.calculate_policy_count(
                policies_qs, date_range
            )
            if bridge_premium_volume > 0:
                average_commission_rate = (
                    bridge_commission_revenue / bridge_premium_volume
                ) * Decimal("100")
            else:
                average_commission_rate = Decimal("0")

            # Count active policies
            active_policies_count = policies_qs.filter(policy_active=True).count()

            return {
                # Month-based bridge components
                "planned_premium_volume": planned_premium_volume,
                "actual_premium_volume": actual_premium_volume,
                "planned_commission_revenue": planned_commission_revenue,
                "actual_commission_revenue": actual_commission_revenue,
                "planned_insurance_sum": planned_insurance_sum,
                "actual_insurance_sum": actual_insurance_sum,
                # Bridge totals (actual closed months + planned current/future)
                "total_premium_volume": bridge_premium_volume,
                "total_commission_revenue": bridge_commission_revenue,
                "total_policy_count": total_policy_count,
                "total_insurance_sum": bridge_insurance_sum,
                "average_commission_rate": average_commission_rate,
                "active_policies_count": active_policies_count,
                "bridge_model": "month_boundary",
                "bridge_cutoff_month_start": current_month_start,
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            # Log error and return empty metrics
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating dashboard metrics: {e}")

            return {
                "planned_premium_volume": Decimal("0"),
                "actual_premium_volume": Decimal("0"),
                "planned_commission_revenue": Decimal("0"),
                "actual_commission_revenue": Decimal("0"),
                "planned_insurance_sum": Decimal("0"),
                "actual_insurance_sum": Decimal("0"),
                "total_premium_volume": Decimal("0"),
                "total_commission_revenue": Decimal("0"),
                "total_policy_count": 0,
                "total_insurance_sum": Decimal("0"),
                "average_commission_rate": Decimal("0"),
                "active_policies_count": 0,
                "bridge_model": "month_boundary",
                "bridge_cutoff_month_start": None,
                "filter_applied": False,
                "error": str(e),
            }

    def get_branch_analytics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get analytics data grouped by branch.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing branch analytics
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from apps.insurers.models import Branch

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)
            policy_count_map = self._build_policy_count_map(policies_qs, "branch_id")
            if not policy_count_map:
                return {
                    "branch_metrics": [],
                    "total_branches": 0,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                }

            payment_metrics_map = self._build_payment_metrics_map(
                payments_qs, "policy__branch_id"
            )
            type_distribution_map = self._build_type_distribution_map(
                policies_qs, "branch_id"
            )

            branch_metrics = []
            branches_with_data = Branch.objects.filter(
                id__in=policy_count_map.keys()
            ).order_by("branch_name")
            for branch in branches_with_data:
                payment_metrics = payment_metrics_map.get(
                    branch.id,
                    {
                        "premium_volume": Decimal("0"),
                        "commission_revenue": Decimal("0"),
                        "insurance_sum": Decimal("0"),
                    },
                )

                branch_metrics.append(
                    {
                        "branch": {"id": branch.id, "name": branch.branch_name},
                        "premium_volume": payment_metrics["premium_volume"],
                        "commission_revenue": payment_metrics["commission_revenue"],
                        "policy_count": policy_count_map.get(branch.id, 0),
                        "insurance_sum": payment_metrics["insurance_sum"],
                        "insurance_type_distribution": type_distribution_map.get(
                            branch.id, {}
                        ),
                    }
                )

            # Calculate market share for each branch
            total_premium = sum(metric["premium_volume"] for metric in branch_metrics)
            total_insurance_sum = sum(
                metric["insurance_sum"] for metric in branch_metrics
            )

            for metric in branch_metrics:
                if total_premium > 0:
                    metric["market_share"] = (
                        metric["premium_volume"] / total_premium
                    ) * Decimal("100")
                else:
                    metric["market_share"] = Decimal("0")

                # Calculate market share by insurance sum
                if total_insurance_sum > 0:
                    metric["market_share_by_sum"] = (
                        metric["insurance_sum"] / total_insurance_sum
                    ) * Decimal("100")
                else:
                    metric["market_share_by_sum"] = Decimal("0")

            return {
                "branch_metrics": branch_metrics,
                "total_branches": len(branch_metrics),
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating branch analytics: {e}")

            return {
                "branch_metrics": [],
                "total_branches": 0,
                "filter_applied": False,
                "error": str(e),
            }

    def get_branch_portfolio_analytics_v2(
        self,
        analytics_filter: Optional[AnalyticsFilter] = None,
        *,
        as_of_date: Optional[date] = None,
        horizon_months: int = 12,
    ) -> Dict[str, Any]:
        """
        Get branch portfolio analytics for active policies (v2 page).

        Focuses on management metrics: active portfolio scale, planned premium/commission,
        risk profile and concentration by branch.
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule

            as_of_date = as_of_date or datetime.now().date()
            horizon_months = max(1, min(int(horizon_months), 36))
            horizon_end = self._add_months(as_of_date, horizon_months)

            # Base querysets for portfolio analytics.
            # The default "active only" behavior is controlled by AnalyticsFilter in view.
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply optional segment filters
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)

            renewal_30_end = as_of_date + timedelta(days=30)
            renewal_60_end = as_of_date + timedelta(days=60)
            renewal_90_end = as_of_date + timedelta(days=90)

            branch_rows = (
                policies_qs.values("branch_id", "branch__branch_name")
                .annotate(
                    active_policies=Count("id"),
                    active_clients=Count("client_id", distinct=True),
                    premium_total=Coalesce(
                        Sum(
                            Subquery(
                                _policy_premium_subquery(), output_field=DecimalField()
                            )
                        ),
                        Decimal("0"),
                    ),
                    renewals_30=Count(
                        "id",
                        filter=Q(
                            end_date__gte=as_of_date,
                            end_date__lte=renewal_30_end,
                        ),
                    ),
                    renewals_60=Count(
                        "id",
                        filter=Q(
                            end_date__gte=as_of_date,
                            end_date__lte=renewal_60_end,
                        ),
                    ),
                    renewals_90=Count(
                        "id",
                        filter=Q(
                            end_date__gte=as_of_date,
                            end_date__lte=renewal_90_end,
                        ),
                    ),
                )
                .order_by("branch__branch_name")
            )

            if not branch_rows:
                return {
                    "as_of_date": as_of_date,
                    "horizon_months": horizon_months,
                    "horizon_end": horizon_end,
                    "summary": {
                        "total_branches": 0,
                        "total_active_policies": 0,
                        "total_active_clients": 0,
                        "total_portfolio_premium": Decimal("0"),
                        "total_planned_premium": Decimal("0"),
                        "total_planned_commission": Decimal("0"),
                        "average_commission_rate": Decimal("0"),
                        "top3_branch_concentration": Decimal("0"),
                        "total_overdue_amount": Decimal("0"),
                        "total_overdue_count": 0,
                        "total_renewals_30": 0,
                        "total_renewals_60": 0,
                        "total_renewals_90": 0,
                    },
                    "branch_metrics": [],
                    "overall_insurance_type_distribution": {},
                    "branch_drilldown": {},
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                }

            # Planned horizon metrics by branch
            horizon_rows = (
                payments_qs.filter(due_date__gte=as_of_date, due_date__lte=horizon_end)
                .values("policy__branch_id")
                .annotate(
                    planned_premium=Coalesce(Sum("amount"), Decimal("0")),
                    planned_commission=Coalesce(Sum("kv_rub"), Decimal("0")),
                )
            )
            horizon_map = {
                int(row["policy__branch_id"]): {
                    "planned_premium": row.get("planned_premium") or Decimal("0"),
                    "planned_commission": row.get("planned_commission") or Decimal("0"),
                }
                for row in horizon_rows
                if row.get("policy__branch_id") is not None
            }

            # Current overdue profile by branch
            overdue_rows = (
                payments_qs.filter(due_date__lt=as_of_date, paid_date__isnull=True)
                .values("policy__branch_id")
                .annotate(
                    overdue_count=Count("id"),
                    overdue_amount=Coalesce(Sum("amount"), Decimal("0")),
                )
            )
            overdue_map = {
                int(row["policy__branch_id"]): {
                    "overdue_count": int(row.get("overdue_count") or 0),
                    "overdue_amount": row.get("overdue_amount") or Decimal("0"),
                }
                for row in overdue_rows
                if row.get("policy__branch_id") is not None
            }

            # Insurance type distributions
            type_rows = (
                policies_qs.values("branch_id", "insurance_type__name")
                .annotate(count=Count("id"))
                .order_by("branch_id", "-count", "insurance_type__name")
            )
            type_map: Dict[int, Dict[str, int]] = defaultdict(dict)
            for row in type_rows:
                branch_id = row.get("branch_id")
                if branch_id is None:
                    continue
                type_name = row.get("insurance_type__name") or "Не указан вид"
                type_map[int(branch_id)][type_name] = int(row.get("count") or 0)

            overall_type_rows = (
                policies_qs.values("insurance_type__name")
                .annotate(count=Count("id"))
                .order_by("-count", "insurance_type__name")
            )
            overall_distribution = {}
            for row in overall_type_rows:
                type_name = row.get("insurance_type__name") or "Не указан вид"
                overall_distribution[type_name] = int(row.get("count") or 0)
            overall_distribution = sort_insurance_types(overall_distribution)

            # Drill-down: top clients per branch
            client_rows = (
                policies_qs.values("branch_id", "client__client_name")
                .annotate(
                    policy_count=Count("id"),
                    premium_total=Coalesce(
                        Sum(
                            Subquery(
                                _policy_premium_subquery(), output_field=DecimalField()
                            )
                        ),
                        Decimal("0"),
                    ),
                )
                .order_by("branch_id", "-premium_total", "client__client_name")
            )
            top_clients_by_branch: Dict[int, list] = defaultdict(list)
            for row in client_rows:
                branch_id = row.get("branch_id")
                if branch_id is None:
                    continue
                top_clients_by_branch[int(branch_id)].append(
                    {
                        "client_name": row.get("client__client_name") or "Не указан",
                        "policy_count": int(row.get("policy_count") or 0),
                        "premium_total": row.get("premium_total") or Decimal("0"),
                    }
                )

            # Drill-down: top insurers per branch
            insurer_rows = (
                policies_qs.values("branch_id", "insurer__insurer_name")
                .annotate(
                    policy_count=Count("id"),
                    premium_total=Coalesce(
                        Sum(
                            Subquery(
                                _policy_premium_subquery(), output_field=DecimalField()
                            )
                        ),
                        Decimal("0"),
                    ),
                )
                .order_by("branch_id", "-premium_total", "insurer__insurer_name")
            )
            top_insurers_by_branch: Dict[int, list] = defaultdict(list)
            for row in insurer_rows:
                branch_id = row.get("branch_id")
                if branch_id is None:
                    continue
                top_insurers_by_branch[int(branch_id)].append(
                    {
                        "insurer_name": row.get("insurer__insurer_name") or "Не указан",
                        "policy_count": int(row.get("policy_count") or 0),
                        "premium_total": row.get("premium_total") or Decimal("0"),
                    }
                )

            # Drill-down: upcoming renewals (nearest).
            # annotate premium_db чтобы избежать N+1 — иначе @property
            # Policy.premium_total делал бы Sum-запрос на каждый полис.
            upcoming_rows = (
                policies_qs.filter(
                    end_date__gte=as_of_date, end_date__lte=renewal_90_end
                )
                .select_related("branch", "client", "insurer")
                .annotate(
                    premium_db=Coalesce(
                        Subquery(
                            _policy_premium_subquery(), output_field=DecimalField()
                        ),
                        Decimal("0"),
                    )
                )
                .order_by("end_date", "policy_number")
            )
            upcoming_by_branch: Dict[int, list] = defaultdict(list)
            for policy in upcoming_rows:
                branch_id = policy.branch_id
                if len(upcoming_by_branch[branch_id]) >= 8:
                    continue
                upcoming_by_branch[branch_id].append(
                    {
                        "policy_number": policy.policy_number,
                        "client_name": policy.client.client_name,
                        "insurer_name": policy.insurer.insurer_name,
                        "end_date": policy.end_date,
                        "premium_total": policy.premium_db or Decimal("0"),
                    }
                )

            # Build branch metric rows
            branch_metrics = []
            for row in branch_rows:
                branch_id = row.get("branch_id")
                if branch_id is None:
                    continue
                branch_id = int(branch_id)

                planned_data = horizon_map.get(
                    branch_id,
                    {
                        "planned_premium": Decimal("0"),
                        "planned_commission": Decimal("0"),
                    },
                )
                overdue_data = overdue_map.get(
                    branch_id,
                    {
                        "overdue_count": 0,
                        "overdue_amount": Decimal("0"),
                    },
                )

                planned_premium = planned_data["planned_premium"]
                planned_commission = planned_data["planned_commission"]
                premium_total = row.get("premium_total") or Decimal("0")
                commission_rate = (
                    (planned_commission / planned_premium) * Decimal("100")
                    if planned_premium > 0
                    else Decimal("0")
                )

                top_clients = top_clients_by_branch.get(branch_id, [])
                top3_clients_total = sum(
                    (client["premium_total"] for client in top_clients[:3]),
                    Decimal("0"),
                )
                concentration_top3_clients = (
                    (top3_clients_total / premium_total) * Decimal("100")
                    if premium_total > 0
                    else Decimal("0")
                )

                branch_metrics.append(
                    {
                        "branch": {
                            "id": branch_id,
                            "name": row.get("branch__branch_name") or "Не указан",
                        },
                        "active_policies": int(row.get("active_policies") or 0),
                        "active_clients": int(row.get("active_clients") or 0),
                        "portfolio_premium": premium_total,
                        "planned_premium": planned_premium,
                        "planned_commission": planned_commission,
                        "commission_rate": commission_rate,
                        "overdue_count": overdue_data["overdue_count"],
                        "overdue_amount": overdue_data["overdue_amount"],
                        "renewals_30": int(row.get("renewals_30") or 0),
                        "renewals_60": int(row.get("renewals_60") or 0),
                        "renewals_90": int(row.get("renewals_90") or 0),
                        "insurance_type_distribution": sort_insurance_types(
                            type_map.get(branch_id, {})
                        ),
                        "concentration_top3_clients": concentration_top3_clients,
                    }
                )

            branch_metrics.sort(
                key=lambda item: (
                    item["planned_premium"],
                    item["portfolio_premium"],
                    item["active_policies"],
                ),
                reverse=True,
            )

            total_planned_premium = sum(
                (item["planned_premium"] for item in branch_metrics), Decimal("0")
            )
            total_planned_commission = sum(
                (item["planned_commission"] for item in branch_metrics), Decimal("0")
            )
            total_portfolio_premium = sum(
                (item["portfolio_premium"] for item in branch_metrics), Decimal("0")
            )

            market_share_base = (
                total_planned_premium
                if total_planned_premium > 0
                else total_portfolio_premium
            )
            for item in branch_metrics:
                item_base = (
                    item["planned_premium"]
                    if total_planned_premium > 0
                    else item["portfolio_premium"]
                )
                item["market_share"] = (
                    (item_base / market_share_base) * Decimal("100")
                    if market_share_base > 0
                    else Decimal("0")
                )

            top3_branch_total = sum(
                (
                    (
                        item["planned_premium"]
                        if total_planned_premium > 0
                        else item["portfolio_premium"]
                    )
                    for item in branch_metrics[:3]
                ),
                Decimal("0"),
            )
            top3_branch_concentration = (
                (top3_branch_total / market_share_base) * Decimal("100")
                if market_share_base > 0
                else Decimal("0")
            )

            total_active_policies = sum(
                (item["active_policies"] for item in branch_metrics), 0
            )
            total_active_clients = sum(
                (item["active_clients"] for item in branch_metrics), 0
            )
            total_overdue_count = sum(
                (item["overdue_count"] for item in branch_metrics), 0
            )
            total_overdue_amount = sum(
                (item["overdue_amount"] for item in branch_metrics), Decimal("0")
            )
            total_renewals_30 = sum((item["renewals_30"] for item in branch_metrics), 0)
            total_renewals_60 = sum((item["renewals_60"] for item in branch_metrics), 0)
            total_renewals_90 = sum((item["renewals_90"] for item in branch_metrics), 0)

            average_commission_rate = (
                (total_planned_commission / total_planned_premium) * Decimal("100")
                if total_planned_premium > 0
                else Decimal("0")
            )

            # Build drill-down map
            branch_drilldown = {}
            for item in branch_metrics:
                branch_id = item["branch"]["id"]
                branch_drilldown[str(branch_id)] = {
                    "top_clients": top_clients_by_branch.get(branch_id, [])[:10],
                    "top_insurers": top_insurers_by_branch.get(branch_id, [])[:6],
                    "upcoming_renewals": upcoming_by_branch.get(branch_id, []),
                }

            return {
                "as_of_date": as_of_date,
                "horizon_months": horizon_months,
                "horizon_end": horizon_end,
                "summary": {
                    "total_branches": len(branch_metrics),
                    "total_active_policies": total_active_policies,
                    "total_active_clients": total_active_clients,
                    "total_portfolio_premium": total_portfolio_premium,
                    "total_planned_premium": total_planned_premium,
                    "total_planned_commission": total_planned_commission,
                    "average_commission_rate": average_commission_rate,
                    "top3_branch_concentration": top3_branch_concentration,
                    "total_overdue_amount": total_overdue_amount,
                    "total_overdue_count": total_overdue_count,
                    "total_renewals_30": total_renewals_30,
                    "total_renewals_60": total_renewals_60,
                    "total_renewals_90": total_renewals_90,
                },
                "branch_metrics": branch_metrics,
                "overall_insurance_type_distribution": overall_distribution,
                "branch_drilldown": branch_drilldown,
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating branch portfolio analytics v2: {e}")

            return {
                "as_of_date": as_of_date or datetime.now().date(),
                "horizon_months": horizon_months,
                "horizon_end": self._add_months(
                    as_of_date or datetime.now().date(), horizon_months
                ),
                "summary": {
                    "total_branches": 0,
                    "total_active_policies": 0,
                    "total_active_clients": 0,
                    "total_portfolio_premium": Decimal("0"),
                    "total_planned_premium": Decimal("0"),
                    "total_planned_commission": Decimal("0"),
                    "average_commission_rate": Decimal("0"),
                    "top3_branch_concentration": Decimal("0"),
                    "total_overdue_amount": Decimal("0"),
                    "total_overdue_count": 0,
                    "total_renewals_30": 0,
                    "total_renewals_60": 0,
                    "total_renewals_90": 0,
                },
                "branch_metrics": [],
                "overall_insurance_type_distribution": {},
                "branch_drilldown": {},
                "filter_applied": False,
                "error": str(e),
            }

    def get_insurer_analytics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get analytics data grouped by insurer.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing insurer analytics
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from apps.insurers.models import Insurer

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)
            policy_count_map = self._build_policy_count_map(policies_qs, "insurer_id")
            if not policy_count_map:
                return {
                    "insurer_metrics": [],
                    "total_insurers": 0,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                }

            payment_metrics_map = self._build_payment_metrics_map(
                payments_qs, "policy__insurer_id"
            )
            type_distribution_map = self._build_type_distribution_map(
                policies_qs, "insurer_id"
            )

            insurer_metrics = []
            total_premium = Decimal("0")
            total_insurance_sum = Decimal("0")

            insurers_with_data = Insurer.objects.filter(
                id__in=policy_count_map.keys()
            ).order_by("insurer_name")
            for insurer in insurers_with_data:
                payment_metrics = payment_metrics_map.get(
                    insurer.id,
                    {
                        "premium_volume": Decimal("0"),
                        "commission_revenue": Decimal("0"),
                        "insurance_sum": Decimal("0"),
                    },
                )
                premium_volume = payment_metrics["premium_volume"]
                insurance_sum = payment_metrics["insurance_sum"]

                total_premium += premium_volume
                total_insurance_sum += insurance_sum

                insurer_metrics.append(
                    {
                        "insurer": insurer,  # Полный объект для страницы аналитики
                        "premium_volume": premium_volume,
                        "commission_revenue": payment_metrics["commission_revenue"],
                        "policy_count": policy_count_map.get(insurer.id, 0),
                        "insurance_sum": insurance_sum,
                        "insurance_type_distribution": type_distribution_map.get(
                            insurer.id, {}
                        ),
                    }
                )

            # Calculate market share
            for metric in insurer_metrics:
                if total_premium > 0:
                    metric["market_share"] = (
                        metric["premium_volume"] / total_premium
                    ) * Decimal("100")
                else:
                    metric["market_share"] = Decimal("0")

                # Calculate market share by insurance sum
                if total_insurance_sum > 0:
                    metric["market_share_by_sum"] = (
                        metric["insurance_sum"] / total_insurance_sum
                    ) * Decimal("100")
                else:
                    metric["market_share_by_sum"] = Decimal("0")

            return {
                "insurer_metrics": insurer_metrics,
                "total_insurers": len(insurer_metrics),
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating insurer analytics: {e}")

            return {
                "insurer_metrics": [],
                "total_insurers": 0,
                "filter_applied": False,
                "error": str(e),
            }

    def get_insurer_analytics_for_charts(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get analytics data grouped by insurer formatted for charts.
        Returns simplified insurer data (id, name only) for chart generation.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing insurer analytics with simplified insurer data
        """
        try:
            insurer_data = self.get_insurer_analytics(analytics_filter)
            insurer_metrics = insurer_data.get("insurer_metrics", [])

            chart_ready_metrics = []
            for metric in insurer_metrics:
                insurer = metric.get("insurer")
                chart_ready_metrics.append(
                    {
                        "insurer": {
                            "id": insurer.id if insurer else None,
                            "name": insurer.insurer_name
                            if insurer
                            else "Неизвестный страховщик",
                        },
                        "premium_volume": metric["premium_volume"],
                        "commission_revenue": metric["commission_revenue"],
                        "policy_count": metric["policy_count"],
                        "insurance_sum": metric["insurance_sum"],
                        "insurance_type_distribution": metric[
                            "insurance_type_distribution"
                        ],
                        "market_share": metric.get("market_share", Decimal("0")),
                        "market_share_by_sum": metric.get(
                            "market_share_by_sum", Decimal("0")
                        ),
                    }
                )

            response = {
                "insurer_metrics": chart_ready_metrics,
                "total_insurers": insurer_data.get("total_insurers", 0),
                "filter_applied": insurer_data.get("filter_applied", False),
            }
            if "error" in insurer_data:
                response["error"] = insurer_data["error"]
            return response

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating insurer analytics for charts: {e}")

            return {
                "insurer_metrics": [],
                "total_insurers": 0,
                "filter_applied": False,
                "error": str(e),
            }

    def get_top_insurers_table(
        self, analytics_filter: Optional[AnalyticsFilter] = None, limit: int = 5
    ) -> list:
        """
        Get top insurers for dashboard table in month-based bridge mode.

        Returns list sorted by bridge premium (actual closed months + planned current/future).
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            from apps.policies.models import Policy, PaymentSchedule
            from apps.insurers.models import Insurer

            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)

            _, _, current_month_start = self._split_bridge_payments_by_month_boundary(
                payments_qs
            )

            insurer_ids = list(
                policies_qs.order_by().values_list("insurer_id", flat=True).distinct()
            )
            if not insurer_ids:
                return []

            insurers_with_data = Insurer.objects.filter(id__in=insurer_ids).order_by(
                "insurer_name"
            )

            planned_metrics_map = self._build_payment_metrics_map(
                payments_qs.filter(due_date__gte=current_month_start),
                "policy__insurer_id",
                include_insurance_sum=False,
            )
            actual_metrics_map = self._build_payment_metrics_map(
                payments_qs.filter(
                    due_date__lt=current_month_start,
                    paid_date__isnull=False,
                ),
                "policy__insurer_id",
                include_insurance_sum=False,
            )

            rows = []
            for insurer in insurers_with_data:
                planned_metrics = planned_metrics_map.get(
                    insurer.id,
                    {
                        "premium_volume": Decimal("0"),
                        "commission_revenue": Decimal("0"),
                        "insurance_sum": Decimal("0"),
                    },
                )
                actual_metrics = actual_metrics_map.get(
                    insurer.id,
                    {
                        "premium_volume": Decimal("0"),
                        "commission_revenue": Decimal("0"),
                        "insurance_sum": Decimal("0"),
                    },
                )

                planned = planned_metrics["premium_volume"]
                actual = actual_metrics["premium_volume"]
                bridge_premium = planned + actual

                planned_commission = planned_metrics["commission_revenue"]
                actual_commission = actual_metrics["commission_revenue"]
                bridge_commission = planned_commission + actual_commission

                rows.append(
                    {
                        "name": insurer.insurer_name,
                        "fact_premium": actual,
                        "plan_premium": planned,
                        "bridge_premium": bridge_premium,
                        "bridge_commission": bridge_commission,
                        # Backward-compatible keys
                        "planned_premium": planned,
                        "actual_premium": actual,
                        "commission": bridge_commission,
                    }
                )

            rows.sort(key=lambda r: r["bridge_premium"], reverse=True)
            return rows[:limit]

        except Exception as e:
            logger.error(f"Error calculating top insurers table: {e}")
            return []

    def get_client_analytics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get analytics data grouped by client with rankings and top lists.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing client analytics with top lists and distributions
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from apps.clients.models import Client

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)
            policy_count_map = self._build_policy_count_map(policies_qs, "client_id")
            if not policy_count_map:
                return {
                    "top_clients_by_insurance_sum": [],
                    "top_clients_by_premium": [],
                    "top_clients_by_commission": [],
                    "top_clients_by_policy_count": [],
                    "client_distribution_by_branch": {},
                    "client_distribution_by_insurance_type": {},
                    "all_client_metrics": [],
                    "total_clients": 0,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                }

            payment_metrics_map = self._build_payment_metrics_map(
                payments_qs, "policy__client_id"
            )
            type_distribution_map = self._build_type_distribution_map(
                policies_qs, "client_id"
            )

            branch_distribution_rows = (
                policies_qs.values("client_id", "branch__branch_name")
                .annotate(count=Count("id"))
                .order_by("client_id", "-count", "branch__branch_name")
            )
            branch_distribution_map: Dict[int, Dict[str, int]] = defaultdict(dict)
            for row in branch_distribution_rows:
                client_id = row.get("client_id")
                if client_id is None:
                    continue
                branch_name = row.get("branch__branch_name") or "Не указан филиал"
                branch_distribution_map[int(client_id)][branch_name] = int(
                    row.get("count") or 0
                )

            clients_with_data = Client.objects.filter(
                id__in=policy_count_map.keys()
            ).order_by("client_name")
            client_metrics = []

            for client in clients_with_data:
                payment_metrics = payment_metrics_map.get(
                    client.id,
                    {
                        "premium_volume": Decimal("0"),
                        "commission_revenue": Decimal("0"),
                        "insurance_sum": Decimal("0"),
                    },
                )
                policy_count = policy_count_map.get(client.id, 0)
                insurance_sum = payment_metrics["insurance_sum"]
                average_policy_value = (
                    insurance_sum / Decimal(str(policy_count))
                    if policy_count > 0
                    else Decimal("0")
                )

                branch_distribution = branch_distribution_map.get(client.id, {})
                primary_branch = (
                    max(branch_distribution.items(), key=lambda x: x[1])[0]
                    if branch_distribution
                    else None
                )

                client_metrics.append(
                    {
                        "client": {
                            "id": client.id,
                            "name": client.client_name,
                            "inn": getattr(
                                client, "inn", getattr(client, "client_inn", "")
                            ),
                            "contact_person": getattr(client, "contact_person", ""),
                        },
                        "premium_volume": payment_metrics["premium_volume"],
                        "commission_revenue": payment_metrics["commission_revenue"],
                        "policy_count": policy_count,
                        "insurance_sum": insurance_sum,
                        "average_policy_value": average_policy_value,
                        "insurance_type_distribution": type_distribution_map.get(
                            client.id, {}
                        ),
                        "branch_distribution": branch_distribution,
                        "primary_branch": primary_branch,
                    }
                )

            # Create top lists by different criteria
            top_clients_by_insurance_sum = sorted(
                client_metrics, key=lambda x: x["insurance_sum"], reverse=True
            )[
                :20
            ]  # Top 20 clients

            top_clients_by_premium = sorted(
                client_metrics, key=lambda x: x["premium_volume"], reverse=True
            )[
                :20
            ]  # Top 20 clients

            top_clients_by_commission = sorted(
                client_metrics, key=lambda x: x["commission_revenue"], reverse=True
            )[
                :20
            ]  # Top 20 clients

            top_clients_by_policy_count = sorted(
                client_metrics, key=lambda x: x["policy_count"], reverse=True
            )[
                :20
            ]  # Top 20 clients

            # Calculate client distribution by branch
            client_distribution_by_branch = {}
            for client_metric in client_metrics:
                for branch_name, count in client_metric["branch_distribution"].items():
                    if branch_name in client_distribution_by_branch:
                        client_distribution_by_branch[branch_name] += 1
                    else:
                        client_distribution_by_branch[branch_name] = 1

            # Calculate client distribution by insurance type (unique clients per type)
            client_distribution_by_insurance_type = {}
            for client_metric in client_metrics:
                # Get all insurance types for this client (unique)
                client_insurance_types = set(
                    client_metric["insurance_type_distribution"].keys()
                )

                # Count this client once for each insurance type they have
                for insurance_type_name in client_insurance_types:
                    if insurance_type_name in client_distribution_by_insurance_type:
                        client_distribution_by_insurance_type[insurance_type_name] += 1
                    else:
                        client_distribution_by_insurance_type[insurance_type_name] = 1

            return {
                "top_clients_by_insurance_sum": top_clients_by_insurance_sum,
                "top_clients_by_premium": top_clients_by_premium,
                "top_clients_by_commission": top_clients_by_commission,
                "top_clients_by_policy_count": top_clients_by_policy_count,
                "client_distribution_by_branch": client_distribution_by_branch,
                "client_distribution_by_insurance_type": client_distribution_by_insurance_type,
                "all_client_metrics": client_metrics,  # Add all client metrics for correct totals
                "total_clients": len(client_metrics),
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating client analytics: {e}")

            return {
                "top_clients_by_insurance_sum": [],
                "top_clients_by_premium": [],
                "top_clients_by_commission": [],
                "top_clients_by_policy_count": [],
                "client_distribution_by_branch": {},
                "client_distribution_by_insurance_type": {},
                "all_client_metrics": [],  # Add empty list for error case
                "total_clients": 0,
                "filter_applied": False,
                "error": str(e),
            }

    def get_financial_analytics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get financial analytics with forecasting and payment analysis.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing financial analytics
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from datetime import datetime, timedelta
            from django.db.models import Q, Case, When, Value, CharField
            from django.utils import timezone

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)
                date_range = analytics_filter.get_date_range_dict()
            else:
                date_range = None

            # Generate monthly forecasts - determine how far to forecast based on future payments
            monthly_premium_forecast = []
            monthly_commission_forecast = []

            current_date = datetime.now().date()

            # Get all future payments to ensure we include them all
            future_payments = payments_qs.filter(due_date__gt=current_date)

            # Find the furthest future payment to determine forecast period
            furthest_payment = future_payments.order_by("-due_date").first()
            if furthest_payment:
                # Calculate months between now and furthest payment, with minimum of 12 months
                months_diff = (
                    furthest_payment.due_date.year - current_date.year
                ) * 12 + (furthest_payment.due_date.month - current_date.month)
                forecast_months = max(
                    12, months_diff + 3
                )  # +3 to ensure we include the month of the furthest payment
            else:
                forecast_months = 12  # Default to 12 months if no future payments

            # Track which payments have been included to ensure we don't miss any
            included_payment_ids = set()

            for i in range(forecast_months):
                # Calculate forecast month - use first day of month for consistency
                if i == 0:
                    # Start from current month
                    forecast_month = current_date.replace(day=1)
                else:
                    # Add months properly handling year boundaries
                    year = current_date.year
                    month = current_date.month + i
                    while month > 12:
                        month -= 12
                        year += 1
                    forecast_month = current_date.replace(year=year, month=month, day=1)

                # Get payments due in this month - use proper month boundaries
                month_start = forecast_month
                if forecast_month.month == 12:
                    month_end = forecast_month.replace(
                        year=forecast_month.year + 1, month=1, day=1
                    ) - timedelta(days=1)
                else:
                    month_end = forecast_month.replace(
                        month=forecast_month.month + 1, day=1
                    ) - timedelta(days=1)

                month_payments = payments_qs.filter(
                    due_date__gte=month_start, due_date__lte=month_end
                )

                # Track which payments we've included
                for payment in month_payments:
                    included_payment_ids.add(payment.id)

                # Calculate forecasted amounts
                forecasted_premium = self.calculator.calculate_premium_volume(
                    month_payments
                )
                forecasted_commission = self.calculator.calculate_commission_revenue(
                    month_payments
                )

                # Calculate actual amounts if month is in the past
                actual_premium = None
                actual_commission = None
                if month_end < current_date:
                    paid_payments = month_payments.filter(paid_date__isnull=False)
                    actual_premium = self.calculator.calculate_premium_volume(
                        paid_payments
                    )
                    actual_commission = self.calculator.calculate_commission_revenue(
                        paid_payments
                    )

                monthly_premium_forecast.append(
                    {
                        "month": forecast_month,
                        "forecasted_premium": forecasted_premium,
                        "forecasted_commission": forecasted_commission,
                        "actual_premium": actual_premium,
                        "actual_commission": actual_commission,
                        "confidence_level": Decimal("85.0"),  # Default confidence level
                    }
                )

                monthly_commission_forecast.append(
                    {
                        "month": forecast_month,
                        "forecasted_premium": forecasted_premium,
                        "forecasted_commission": forecasted_commission,
                        "actual_premium": actual_premium,
                        "actual_commission": actual_commission,
                        "confidence_level": Decimal("85.0"),
                    }
                )

            # Check if any future payments were missed and add them to the last month
            missed_payments = future_payments.exclude(id__in=included_payment_ids)
            if missed_payments.exists():
                # Add missed payments to the last forecast month
                if monthly_premium_forecast:
                    last_forecast = monthly_premium_forecast[-1]
                    missed_premium = self.calculator.calculate_premium_volume(
                        missed_payments
                    )
                    missed_commission = self.calculator.calculate_commission_revenue(
                        missed_payments
                    )

                    last_forecast["forecasted_premium"] += missed_premium
                    last_forecast["forecasted_commission"] += missed_commission

                    # Update commission forecast as well
                    monthly_commission_forecast[-1][
                        "forecasted_premium"
                    ] += missed_premium
                    monthly_commission_forecast[-1][
                        "forecasted_commission"
                    ] += missed_commission

            # Build future-oriented forecast blocks for dashboard
            (
                future_forecast_summary,
                future_quarterly_forecast,
            ) = self._build_future_forecast_blocks(
                monthly_premium_forecast, current_date
            )

            # Build current-year bridge block: actual for elapsed months + forecast for remaining
            current_year_outlook = self._build_current_year_outlook(
                payments_qs, current_date
            )

            # Analyze payment statuses
            today = timezone.now().date()

            # Count payments by status (using paid_date field)
            total_payments = payments_qs.count()
            paid_payments = payments_qs.filter(paid_date__isnull=False).count()
            pending_payments = payments_qs.filter(
                paid_date__isnull=True, due_date__gte=today
            ).count()
            overdue_payments = payments_qs.filter(
                paid_date__isnull=True, due_date__lt=today
            ).count()

            # Calculate amounts by status
            paid_amount = self.calculator.calculate_premium_volume(
                payments_qs.filter(paid_date__isnull=False)
            )
            pending_amount = self.calculator.calculate_premium_volume(
                payments_qs.filter(paid_date__isnull=True, due_date__gte=today)
            )
            overdue_amount = self.calculator.calculate_premium_volume(
                payments_qs.filter(paid_date__isnull=True, due_date__lt=today)
            )

            # Calculate payment discipline rate
            if total_payments > 0:
                payment_discipline_rate = (
                    Decimal(str(paid_payments)) / Decimal(str(total_payments))
                ) * Decimal("100")
            else:
                payment_discipline_rate = Decimal("0")

            payment_status_analysis = {
                "total_payments": total_payments,
                "paid_payments": paid_payments,
                "pending_payments": pending_payments,
                "overdue_payments": overdue_payments,
                "paid_amount": paid_amount,
                "pending_amount": pending_amount,
                "overdue_amount": overdue_amount,
                "payment_discipline_rate": payment_discipline_rate,
            }

            # Calculate average commission rates by different dimensions
            average_commission_rates = {}

            # By insurance type (single grouped query)
            insurance_type_rate_rows = (
                payments_qs.values("policy__insurance_type__name")
                .annotate(
                    total_commission=Coalesce(Sum("kv_rub"), Decimal("0")),
                    total_premium=Coalesce(Sum("amount"), Decimal("0")),
                )
                .order_by("policy__insurance_type__name")
            )
            for row in insurance_type_rate_rows:
                type_name = row.get("policy__insurance_type__name") or "Не указан вид"
                total_type_premium = row.get("total_premium") or Decimal("0")
                total_type_commission = row.get("total_commission") or Decimal("0")
                if total_type_premium > 0:
                    avg_rate = (total_type_commission / total_type_premium) * Decimal(
                        "100"
                    )
                else:
                    avg_rate = Decimal("0")
                average_commission_rates[f"insurance_type_{type_name}"] = avg_rate

            # By insurer (single grouped query)
            insurer_rate_rows = (
                payments_qs.values("policy__insurer__insurer_name")
                .annotate(
                    total_commission=Coalesce(Sum("kv_rub"), Decimal("0")),
                    total_premium=Coalesce(Sum("amount"), Decimal("0")),
                )
                .order_by("policy__insurer__insurer_name")
            )
            for row in insurer_rate_rows:
                insurer_name = (
                    row.get("policy__insurer__insurer_name") or "Неизвестный страховщик"
                )
                total_insurer_premium = row.get("total_premium") or Decimal("0")
                total_insurer_commission = row.get("total_commission") or Decimal("0")
                if total_insurer_premium > 0:
                    avg_rate = (
                        total_insurer_commission / total_insurer_premium
                    ) * Decimal("100")
                else:
                    avg_rate = Decimal("0")
                average_commission_rates[f"insurer_{insurer_name}"] = avg_rate

            # Analyze overdue payments
            overdue_payments_qs = payments_qs.filter(
                paid_date__isnull=True, due_date__lt=today
            )

            # Breakdown by days overdue (single grouped query)
            overdue_by_days_rows = (
                overdue_payments_qs.annotate(
                    overdue_bucket=Case(
                        When(
                            due_date__gte=today - timedelta(days=30),
                            then=Value("1-30 days"),
                        ),
                        When(
                            due_date__gte=today - timedelta(days=60),
                            then=Value("31-60 days"),
                        ),
                        When(
                            due_date__gte=today - timedelta(days=90),
                            then=Value("61-90 days"),
                        ),
                        default=Value("90+ days"),
                        output_field=CharField(),
                    )
                )
                .values("overdue_bucket")
                .annotate(total_amount=Coalesce(Sum("amount"), Decimal("0")))
                .order_by()
            )
            overdue_by_days = {
                row["overdue_bucket"]: row["total_amount"] or Decimal("0")
                for row in overdue_by_days_rows
            }

            # Breakdown by branch (single grouped query)
            overdue_by_branch_rows = (
                overdue_payments_qs.values("policy__branch__branch_name")
                .annotate(total_amount=Coalesce(Sum("amount"), Decimal("0")))
                .order_by("policy__branch__branch_name")
            )
            overdue_by_branch = {
                (row.get("policy__branch__branch_name") or "Не указан филиал"): (
                    row.get("total_amount") or Decimal("0")
                )
                for row in overdue_by_branch_rows
            }

            # Breakdown by insurer (single grouped query)
            overdue_by_insurer_rows = (
                overdue_payments_qs.values("policy__insurer__insurer_name")
                .annotate(total_amount=Coalesce(Sum("amount"), Decimal("0")))
                .order_by("policy__insurer__insurer_name")
            )
            overdue_by_insurer = {}
            for row in overdue_by_insurer_rows:
                insurer_name = (
                    row.get("policy__insurer__insurer_name") or "Неизвестный страховщик"
                )
                insurer_total = row.get("total_amount") or Decimal("0")
                if insurer_total > 0:
                    overdue_by_insurer[insurer_name] = insurer_total

            # Calculate average overdue days (single column fetch)
            overdue_due_dates = list(
                overdue_payments_qs.values_list("due_date", flat=True)
            )
            if overdue_due_dates:
                total_overdue_days = sum(
                    (today - due_date).days for due_date in overdue_due_dates
                )
                average_overdue_days = Decimal(str(total_overdue_days)) / Decimal(
                    str(len(overdue_due_dates))
                )
            else:
                average_overdue_days = Decimal("0")

            # Find worst performing clients (by overdue amount)
            worst_client_rows = (
                overdue_payments_qs.values(
                    "policy__client_id",
                    "policy__client__client_name",
                )
                .annotate(
                    overdue_amount=Coalesce(Sum("amount"), Decimal("0")),
                    overdue_count=Count("id"),
                )
                .order_by("-overdue_amount")
            )
            worst_performing_clients = []
            for row in worst_client_rows:
                client_overdue = row.get("overdue_amount") or Decimal("0")
                if client_overdue <= 0:
                    continue
                worst_performing_clients.append(
                    {
                        "client": {
                            "id": row.get("policy__client_id"),
                            "name": row.get("policy__client__client_name")
                            or "Неизвестный клиент",
                            "inn": "",
                            "contact_person": "",
                        },
                        "overdue_amount": client_overdue,
                        "overdue_count": int(row.get("overdue_count") or 0),
                    }
                )
                if len(worst_performing_clients) >= 10:
                    break

            overdue_payments_analysis = {
                "total_overdue_amount": overdue_amount,
                "overdue_by_days": overdue_by_days,
                "overdue_by_branch": overdue_by_branch,
                "overdue_by_insurer": overdue_by_insurer,
                "average_overdue_days": average_overdue_days,
                "worst_performing_clients": worst_performing_clients,
            }

            # Calculate seasonal analysis
            seasonal_analysis = self._calculate_seasonal_analysis(
                monthly_premium_forecast, analytics_filter
            )

            # Calculate comparative analysis (year-over-year)
            comparative_analysis = self._calculate_comparative_analysis(
                analytics_filter
            )

            return {
                "monthly_premium_forecast": monthly_premium_forecast,
                "monthly_commission_forecast": monthly_commission_forecast,
                "payment_status_analysis": payment_status_analysis,
                "average_commission_rates": average_commission_rates,
                "overdue_payments_analysis": overdue_payments_analysis,
                "seasonal_analysis": seasonal_analysis,
                "comparative_analysis": comparative_analysis,
                "future_forecast_summary": future_forecast_summary,
                "future_quarterly_forecast": future_quarterly_forecast,
                "current_year_outlook": current_year_outlook,
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating financial analytics: {e}")

            return {
                "monthly_premium_forecast": [],
                "monthly_commission_forecast": [],
                "payment_status_analysis": {
                    "total_payments": 0,
                    "paid_payments": 0,
                    "pending_payments": 0,
                    "overdue_payments": 0,
                    "paid_amount": Decimal("0"),
                    "pending_amount": Decimal("0"),
                    "overdue_amount": Decimal("0"),
                    "payment_discipline_rate": Decimal("0"),
                },
                "average_commission_rates": {},
                "overdue_payments_analysis": {
                    "total_overdue_amount": Decimal("0"),
                    "overdue_by_days": {},
                    "overdue_by_branch": {},
                    "overdue_by_insurer": {},
                    "average_overdue_days": Decimal("0"),
                    "worst_performing_clients": [],
                },
                "seasonal_analysis": {
                    "monthly_averages": {},
                    "seasonal_indices": {},
                    "peak_months": [],
                    "low_months": [],
                    "quarterly_data": {},
                    "seasonality_strength": Decimal("0"),
                    "overall_average": Decimal("0"),
                },
                "comparative_analysis": {
                    "current_year": datetime.now().year,
                    "previous_year": datetime.now().year - 1,
                    "premium_growth": Decimal("0"),
                    "commission_growth": Decimal("0"),
                    "policy_growth": Decimal("0"),
                    "current_premium": Decimal("0"),
                    "previous_premium": Decimal("0"),
                    "current_commission": Decimal("0"),
                    "previous_commission": Decimal("0"),
                    "current_policy_count": 0,
                    "previous_policy_count": 0,
                    "insurance_type_changes": {},
                    "new_clients": 0,
                    "returning_clients": 0,
                    "new_clients_percentage": Decimal("0"),
                },
                "future_forecast_summary": {
                    "as_of_date": datetime.now().date(),
                    "horizon_months": 0,
                    "total_future_premium": Decimal("0"),
                    "total_future_commission": Decimal("0"),
                    "current_month": None,
                    "next_month": None,
                    "current_quarter_remaining": None,
                    "next_quarter": None,
                },
                "future_quarterly_forecast": [],
                "current_year_outlook": {
                    "year": datetime.now().year,
                    "current_month": datetime.now().month,
                    "ytd_actual_premium": Decimal("0"),
                    "ytd_actual_commission": Decimal("0"),
                    "remaining_forecast_premium": Decimal("0"),
                    "remaining_forecast_commission": Decimal("0"),
                    "projected_full_year_premium": Decimal("0"),
                    "projected_full_year_commission": Decimal("0"),
                    "ytd_months_count": 0,
                    "forecast_months_count": 0,
                    "monthly_breakdown": [],
                },
                "filter_applied": False,
                "error": str(e),
            }

    def _build_future_forecast_blocks(self, monthly_forecast, current_date):
        """Build summary and quarterly breakdown for future forecast periods."""
        if not monthly_forecast:
            return (
                {
                    "as_of_date": current_date,
                    "horizon_months": 0,
                    "total_future_premium": Decimal("0"),
                    "total_future_commission": Decimal("0"),
                    "current_month": None,
                    "next_month": None,
                    "current_quarter_remaining": None,
                    "next_quarter": None,
                },
                [],
            )

        # Global totals for the whole forecast horizon
        total_future_premium = sum(
            item["forecasted_premium"] for item in monthly_forecast
        )
        total_future_commission = sum(
            item["forecasted_commission"] for item in monthly_forecast
        )

        # Quarter aggregation
        quarter_map = {}
        for item in monthly_forecast:
            month_date = item["month"]
            quarter_number = ((month_date.month - 1) // 3) + 1
            key = (month_date.year, quarter_number)

            if key not in quarter_map:
                quarter_map[key] = {
                    "year": month_date.year,
                    "quarter_number": quarter_number,
                    "quarter_label": f"Q{quarter_number} {month_date.year}",
                    "forecasted_premium": Decimal("0"),
                    "forecasted_commission": Decimal("0"),
                    "months_count": 0,
                    "start_month": month_date,
                    "end_month": month_date,
                }

            quarter_map[key]["forecasted_premium"] += item["forecasted_premium"]
            quarter_map[key]["forecasted_commission"] += item["forecasted_commission"]
            quarter_map[key]["months_count"] += 1
            quarter_map[key]["end_month"] = month_date

        future_quarterly_forecast = [
            quarter_map[key] for key in sorted(quarter_map.keys())
        ]

        current_quarter_number = ((current_date.month - 1) // 3) + 1
        current_quarter_key = (current_date.year, current_quarter_number)

        if current_quarter_number == 4:
            next_quarter_key = (current_date.year + 1, 1)
        else:
            next_quarter_key = (current_date.year, current_quarter_number + 1)

        current_quarter_remaining = quarter_map.get(current_quarter_key)
        next_quarter = quarter_map.get(next_quarter_key)

        summary = {
            "as_of_date": current_date,
            "horizon_months": len(monthly_forecast),
            "total_future_premium": total_future_premium,
            "total_future_commission": total_future_commission,
            "current_month": monthly_forecast[0] if monthly_forecast else None,
            "next_month": monthly_forecast[1] if len(monthly_forecast) > 1 else None,
            "current_quarter_remaining": current_quarter_remaining,
            "next_quarter": next_quarter,
        }

        return summary, future_quarterly_forecast

    def _build_current_year_outlook(self, payments_qs, current_date):
        """
        Build current-year bridge:
        elapsed months as actual (paid), remaining months as forecast (scheduled).
        """
        current_year = current_date.year
        current_month = current_date.month
        month_names_ru = {
            1: "Январь",
            2: "Февраль",
            3: "Март",
            4: "Апрель",
            5: "Май",
            6: "Июнь",
            7: "Июль",
            8: "Август",
            9: "Сентябрь",
            10: "Октябрь",
            11: "Ноябрь",
            12: "Декабрь",
        }
        month_short_ru = {
            1: "Янв",
            2: "Фев",
            3: "Мар",
            4: "Апр",
            5: "Май",
            6: "Июн",
            7: "Июл",
            8: "Авг",
            9: "Сен",
            10: "Окт",
            11: "Ноя",
            12: "Дек",
        }

        monthly_breakdown = []
        ytd_actual_premium = Decimal("0")
        ytd_actual_commission = Decimal("0")
        remaining_forecast_premium = Decimal("0")
        remaining_forecast_commission = Decimal("0")

        for month in range(1, 13):
            month_start = date(current_year, month, 1)
            if month == 12:
                month_end = date(current_year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(current_year, month + 1, 1) - timedelta(days=1)

            month_payments = payments_qs.filter(
                due_date__gte=month_start, due_date__lte=month_end
            )
            paid_month_payments = month_payments.filter(paid_date__isnull=False)

            actual_premium = self.calculator.calculate_premium_volume(
                paid_month_payments
            )
            actual_commission = self.calculator.calculate_commission_revenue(
                paid_month_payments
            )
            forecasted_premium = self.calculator.calculate_premium_volume(
                month_payments
            )
            forecasted_commission = self.calculator.calculate_commission_revenue(
                month_payments
            )

            is_actual = month < current_month
            premium_value = actual_premium if is_actual else forecasted_premium
            commission_value = actual_commission if is_actual else forecasted_commission

            if is_actual:
                ytd_actual_premium += actual_premium
                ytd_actual_commission += actual_commission
            else:
                remaining_forecast_premium += forecasted_premium
                remaining_forecast_commission += forecasted_commission

            monthly_breakdown.append(
                {
                    "month": month,
                    "month_name": month_names_ru[month],
                    "month_short": month_short_ru[month],
                    "mode": "actual" if is_actual else "forecast",
                    "premium_value": premium_value,
                    "commission_value": commission_value,
                    "actual_premium": actual_premium,
                    "actual_commission": actual_commission,
                    "forecasted_premium": forecasted_premium,
                    "forecasted_commission": forecasted_commission,
                }
            )

        return {
            "year": current_year,
            "current_month": current_month,
            "ytd_actual_premium": ytd_actual_premium,
            "ytd_actual_commission": ytd_actual_commission,
            "remaining_forecast_premium": remaining_forecast_premium,
            "remaining_forecast_commission": remaining_forecast_commission,
            "projected_full_year_premium": ytd_actual_premium
            + remaining_forecast_premium,
            "projected_full_year_commission": ytd_actual_commission
            + remaining_forecast_commission,
            "ytd_months_count": max(0, current_month - 1),
            "forecast_months_count": 13 - current_month,
            "monthly_breakdown": monthly_breakdown,
        }

    def _calculate_seasonal_analysis(
        self, monthly_forecast: list, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Calculate seasonal patterns and analysis.

        Args:
            monthly_forecast: List of monthly forecast data
            analytics_filter: Optional filter for historical data

        Returns:
            Dictionary containing seasonal analysis
        """
        try:
            from apps.policies.models import PaymentSchedule
            from collections import defaultdict
            import calendar

            # Get historical data for seasonal analysis (last 2-3 years)
            current_year = datetime.now().year
            historical_years = [current_year - 2, current_year - 1, current_year]

            payments_qs = PaymentSchedule.objects.filter(
                due_date__year__in=historical_years
            )

            # Apply filters if provided (except date filters)
            if analytics_filter:
                if analytics_filter.branch_ids:
                    payments_qs = payments_qs.filter(
                        policy__branch_id__in=analytics_filter.branch_ids
                    )
                if analytics_filter.insurer_ids:
                    payments_qs = payments_qs.filter(
                        policy__insurer_id__in=analytics_filter.insurer_ids
                    )
                if analytics_filter.insurance_type_ids:
                    payments_qs = payments_qs.filter(
                        policy__insurance_type_id__in=analytics_filter.insurance_type_ids
                    )
                if analytics_filter.client_ids:
                    payments_qs = payments_qs.filter(
                        policy__client_id__in=analytics_filter.client_ids
                    )
                if analytics_filter.policy_active is not None:
                    payments_qs = payments_qs.filter(
                        policy__policy_active=analytics_filter.policy_active
                    )

            # Group by month number (1-12) and calculate averages
            monthly_totals = defaultdict(list)

            for payment in payments_qs:
                month_num = payment.due_date.month
                monthly_totals[month_num].append(payment.amount or Decimal("0"))

            # Calculate monthly averages
            monthly_averages = {}
            for month_num in range(1, 13):
                if month_num in monthly_totals and monthly_totals[month_num]:
                    avg = sum(monthly_totals[month_num]) / len(
                        monthly_totals[month_num]
                    )
                    monthly_averages[month_num] = avg
                else:
                    monthly_averages[month_num] = Decimal("0")

            # Calculate overall average
            overall_avg = (
                sum(monthly_averages.values()) / 12
                if monthly_averages
                else Decimal("0")
            )

            # Calculate seasonal indices
            seasonal_indices = {}
            for month_num, avg in monthly_averages.items():
                if overall_avg > 0:
                    seasonal_indices[month_num] = (avg / overall_avg) * Decimal("100")
                else:
                    seasonal_indices[month_num] = Decimal("100")

            # Find peak and low months
            if monthly_averages:
                sorted_months = sorted(
                    monthly_averages.items(), key=lambda x: x[1], reverse=True
                )
                peak_months = [
                    {"month": month, "name": calendar.month_name[month], "value": value}
                    for month, value in sorted_months[:3]
                ]
                low_months = [
                    {"month": month, "name": calendar.month_name[month], "value": value}
                    for month, value in sorted_months[-3:]
                ]
            else:
                peak_months = []
                low_months = []

            # Calculate quarterly patterns
            quarterly_data = {
                "Q1": sum(monthly_averages[m] for m in [1, 2, 3]) / 3,
                "Q2": sum(monthly_averages[m] for m in [4, 5, 6]) / 3,
                "Q3": sum(monthly_averages[m] for m in [7, 8, 9]) / 3,
                "Q4": sum(monthly_averages[m] for m in [10, 11, 12]) / 3,
            }

            # Calculate seasonality strength (coefficient of variation)
            if overall_avg > 0:
                variance = (
                    sum((avg - overall_avg) ** 2 for avg in monthly_averages.values())
                    / 12
                )
                std_dev = variance ** Decimal("0.5")
                seasonality_strength = (std_dev / overall_avg) * Decimal("100")
            else:
                seasonality_strength = Decimal("0")

            return {
                "monthly_averages": monthly_averages,
                "seasonal_indices": seasonal_indices,
                "peak_months": peak_months,
                "low_months": low_months,
                "quarterly_data": quarterly_data,
                "seasonality_strength": seasonality_strength,
                "overall_average": overall_avg,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating seasonal analysis: {e}")

            return {
                "monthly_averages": {},
                "seasonal_indices": {},
                "peak_months": [],
                "low_months": [],
                "quarterly_data": {},
                "seasonality_strength": Decimal("0"),
                "overall_average": Decimal("0"),
            }

    def _calculate_comparative_analysis(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Calculate year-over-year comparative analysis.

        Args:
            analytics_filter: Optional filter to apply

        Returns:
            Dictionary containing comparative analysis
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from django.db.models import Sum, Count

            current_year = datetime.now().year
            previous_year = current_year - 1

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided (except date filters)
            if analytics_filter:
                if analytics_filter.branch_ids:
                    policies_qs = policies_qs.filter(
                        branch_id__in=analytics_filter.branch_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__branch_id__in=analytics_filter.branch_ids
                    )
                if analytics_filter.insurer_ids:
                    policies_qs = policies_qs.filter(
                        insurer_id__in=analytics_filter.insurer_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__insurer_id__in=analytics_filter.insurer_ids
                    )
                if analytics_filter.insurance_type_ids:
                    policies_qs = policies_qs.filter(
                        insurance_type_id__in=analytics_filter.insurance_type_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__insurance_type_id__in=analytics_filter.insurance_type_ids
                    )
                if analytics_filter.client_ids:
                    policies_qs = policies_qs.filter(
                        client_id__in=analytics_filter.client_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__client_id__in=analytics_filter.client_ids
                    )
                if analytics_filter.policy_active is not None:
                    policies_qs = policies_qs.filter(
                        policy_active=analytics_filter.policy_active
                    )
                    payments_qs = payments_qs.filter(
                        policy__policy_active=analytics_filter.policy_active
                    )

            # Calculate current year metrics
            current_year_payments = payments_qs.filter(due_date__year=current_year)
            current_year_policies = policies_qs.filter(start_date__year=current_year)

            current_premium = current_year_payments.aggregate(total=Sum("amount"))[
                "total"
            ] or Decimal("0")

            current_commission = current_year_payments.aggregate(total=Sum("kv_rub"))[
                "total"
            ] or Decimal("0")

            current_policy_count = current_year_policies.count()

            # Calculate previous year metrics
            previous_year_payments = payments_qs.filter(due_date__year=previous_year)
            previous_year_policies = policies_qs.filter(start_date__year=previous_year)

            previous_premium = previous_year_payments.aggregate(total=Sum("amount"))[
                "total"
            ] or Decimal("0")

            previous_commission = previous_year_payments.aggregate(total=Sum("kv_rub"))[
                "total"
            ] or Decimal("0")

            previous_policy_count = previous_year_policies.count()

            # Calculate growth rates
            def calculate_growth(current, previous):
                if previous > 0:
                    return ((current - previous) / previous) * Decimal("100")
                elif current > 0:
                    return Decimal("100")  # 100% growth from zero
                else:
                    return Decimal("0")

            premium_growth = calculate_growth(current_premium, previous_premium)
            commission_growth = calculate_growth(
                current_commission, previous_commission
            )
            policy_growth = calculate_growth(
                Decimal(str(current_policy_count)), Decimal(str(previous_policy_count))
            )

            # Calculate insurance type distribution changes
            from apps.policies.models import InsuranceType

            insurance_type_changes = {}
            insurance_types = InsuranceType.objects.filter(
                id__in=policies_qs.values_list(
                    "insurance_type_id", flat=True
                ).distinct()
            )

            for ins_type in insurance_types:
                current_count = current_year_policies.filter(
                    insurance_type=ins_type
                ).count()
                previous_count = previous_year_policies.filter(
                    insurance_type=ins_type
                ).count()

                growth = calculate_growth(
                    Decimal(str(current_count)), Decimal(str(previous_count))
                )

                insurance_type_changes[ins_type.name] = {
                    "current": current_count,
                    "previous": previous_count,
                    "growth": growth,
                }

            # Calculate new vs returning clients
            current_year_client_ids = set(
                current_year_policies.values_list("client_id", flat=True)
            )
            previous_year_client_ids = set(
                previous_year_policies.values_list("client_id", flat=True)
            )

            new_clients = len(current_year_client_ids - previous_year_client_ids)
            returning_clients = len(current_year_client_ids & previous_year_client_ids)

            new_clients_percentage = Decimal("0")
            if current_year_client_ids:
                new_clients_percentage = (
                    Decimal(str(new_clients))
                    / Decimal(str(len(current_year_client_ids)))
                ) * Decimal("100")

            return {
                "current_year": current_year,
                "previous_year": previous_year,
                "premium_growth": premium_growth,
                "commission_growth": commission_growth,
                "policy_growth": policy_growth,
                "current_premium": current_premium,
                "previous_premium": previous_premium,
                "current_commission": current_commission,
                "previous_commission": previous_commission,
                "current_policy_count": current_policy_count,
                "previous_policy_count": previous_policy_count,
                "insurance_type_changes": insurance_type_changes,
                "new_clients": new_clients,
                "returning_clients": returning_clients,
                "new_clients_percentage": new_clients_percentage,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating comparative analysis: {e}")

            return {
                "current_year": datetime.now().year,
                "previous_year": datetime.now().year - 1,
                "premium_growth": Decimal("0"),
                "commission_growth": Decimal("0"),
                "policy_growth": Decimal("0"),
                "current_premium": Decimal("0"),
                "previous_premium": Decimal("0"),
                "current_commission": Decimal("0"),
                "previous_commission": Decimal("0"),
                "current_policy_count": 0,
                "previous_policy_count": 0,
                "insurance_type_changes": {},
                "new_clients": 0,
                "returning_clients": 0,
                "new_clients_percentage": Decimal("0"),
            }

    def get_financial_history(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get financial history analytics for completed periods.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing financial history analytics
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from datetime import datetime, timedelta
            from django.db.models import Q, Sum, Count, Avg
            from django.utils import timezone
            import calendar

            # Define the start date (January 2026) and end date (previous month)
            start_date = datetime(2026, 1, 1).date()
            current_date = datetime.now().date()

            # Get the first day of current month, then subtract 1 day to get last day of previous month
            first_day_current_month = current_date.replace(day=1)
            end_date = first_day_current_month - timedelta(days=1)

            # If we're still before January 2026, return empty data
            if current_date < start_date:
                return self._get_empty_financial_history()

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided (except date filters - we control dates)
            if analytics_filter:
                if analytics_filter.branch_ids:
                    policies_qs = policies_qs.filter(
                        branch_id__in=analytics_filter.branch_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__branch_id__in=analytics_filter.branch_ids
                    )
                if analytics_filter.insurer_ids:
                    policies_qs = policies_qs.filter(
                        insurer_id__in=analytics_filter.insurer_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__insurer_id__in=analytics_filter.insurer_ids
                    )
                if analytics_filter.client_ids:
                    policies_qs = policies_qs.filter(
                        client_id__in=analytics_filter.client_ids
                    )
                    payments_qs = payments_qs.filter(
                        policy__client_id__in=analytics_filter.client_ids
                    )
                if analytics_filter.policy_active is not None:
                    policies_qs = policies_qs.filter(
                        policy_active=analytics_filter.policy_active
                    )
                    payments_qs = payments_qs.filter(
                        policy__policy_active=analytics_filter.policy_active
                    )

            # Filter to our date range
            historical_payments = payments_qs.filter(
                due_date__gte=start_date, due_date__lte=end_date
            )

            historical_policies = policies_qs.filter(
                start_date__gte=start_date, start_date__lte=end_date
            )

            # Apply target month filter if specified
            if analytics_filter and analytics_filter.target_month:
                try:
                    # Parse target month (format: "YYYY-MM")
                    year, month = map(int, analytics_filter.target_month.split("-"))

                    # Filter payments to specific month
                    historical_payments = historical_payments.filter(
                        due_date__year=year, due_date__month=month
                    )

                    # Filter policies to specific month
                    historical_policies = historical_policies.filter(
                        start_date__year=year, start_date__month=month
                    )

                    # Update date range for monthly history generation
                    start_date = datetime(year, month, 1).date()
                    if month == 12:
                        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
                    else:
                        end_date = datetime(year, month + 1, 1).date() - timedelta(
                            days=1
                        )

                except (ValueError, TypeError):
                    # Invalid month format, ignore filter
                    pass

            # Generate monthly historical data
            monthly_history = self._generate_monthly_history(
                historical_payments, historical_policies, start_date, end_date
            )

            # Calculate fact vs forecast analysis
            fact_vs_forecast = self._calculate_fact_vs_forecast(
                monthly_history, analytics_filter
            )

            # Calculate performance trends
            performance_trends = self._calculate_performance_trends(monthly_history)

            # Get top events for each month
            monthly_highlights = self._get_monthly_highlights(
                historical_payments,
                historical_policies,
                start_date,
                end_date,
                analytics_filter,
            )

            # Analyze problem areas
            problem_analysis = self._analyze_problem_areas(
                historical_payments, start_date, end_date
            )

            # Calculate dimensional breakdown
            dimensional_breakdown = self._calculate_dimensional_breakdown(
                historical_payments, historical_policies, analytics_filter
            )

            # Calculate summary metrics
            total_actual_premium = sum(
                month["actual_premium"] for month in monthly_history
            )
            total_actual_commission = sum(
                month["actual_commission"] for month in monthly_history
            )
            total_planned_premium = sum(
                month["planned_premium"] for month in monthly_history
            )
            total_planned_commission = sum(
                month["planned_commission"] for month in monthly_history
            )
            total_policies_created = sum(
                month["policies_created"] for month in monthly_history
            )
            total_payments_count = sum(
                month["total_payments"] for month in monthly_history
            )
            total_paid_payments = sum(
                month["paid_payments"] for month in monthly_history
            )
            total_overdue_payments = sum(
                month["overdue_payments"] for month in monthly_history
            )

            # Plan vs fact deltas and collection rate
            premium_deviation_amount = total_actual_premium - total_planned_premium
            commission_deviation_amount = (
                total_actual_commission - total_planned_commission
            )

            if total_planned_premium > 0:
                premium_deviation_percent = (
                    premium_deviation_amount / total_planned_premium
                ) * Decimal("100")
                collection_rate = (
                    total_actual_premium / total_planned_premium
                ) * Decimal("100")
            else:
                premium_deviation_percent = Decimal("0")
                collection_rate = Decimal("0")

            if total_planned_commission > 0:
                commission_deviation_percent = (
                    commission_deviation_amount / total_planned_commission
                ) * Decimal("100")
            else:
                commission_deviation_percent = Decimal("0")

            payment_realization_rate = Decimal("0")
            if total_payments_count > 0:
                payment_realization_rate = (
                    Decimal(str(total_paid_payments))
                    / Decimal(str(total_payments_count))
                ) * Decimal("100")

            average_paid_payment = Decimal("0")
            if total_paid_payments > 0:
                average_paid_payment = total_actual_premium / Decimal(
                    str(total_paid_payments)
                )

            # Calculate average monthly performance
            months_count = len(monthly_history)
            avg_monthly_premium = (
                total_actual_premium / months_count
                if months_count > 0
                else Decimal("0")
            )
            avg_monthly_commission = (
                total_actual_commission / months_count
                if months_count > 0
                else Decimal("0")
            )

            return {
                "monthly_history": monthly_history,
                "fact_vs_forecast": fact_vs_forecast,
                "performance_trends": performance_trends,
                "monthly_highlights": monthly_highlights,
                "problem_analysis": problem_analysis,
                "dimensional_breakdown": dimensional_breakdown,
                "summary_metrics": {
                    "total_actual_premium": total_actual_premium,
                    "total_actual_commission": total_actual_commission,
                    "total_planned_premium": total_planned_premium,
                    "total_planned_commission": total_planned_commission,
                    "premium_deviation_amount": premium_deviation_amount,
                    "premium_deviation_percent": premium_deviation_percent,
                    "commission_deviation_amount": commission_deviation_amount,
                    "commission_deviation_percent": commission_deviation_percent,
                    "collection_rate": collection_rate,
                    "total_payments_count": total_payments_count,
                    "total_paid_payments": total_paid_payments,
                    "total_overdue_payments": total_overdue_payments,
                    "payment_realization_rate": payment_realization_rate,
                    "average_paid_payment": average_paid_payment,
                    "total_policies_created": total_policies_created,
                    "avg_monthly_premium": avg_monthly_premium,
                    "avg_monthly_commission": avg_monthly_commission,
                    "months_analyzed": months_count,
                    "period_start": start_date,
                    "period_end": end_date,
                },
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating financial history: {e}")

            return self._get_empty_financial_history(error=str(e))

    def _generate_monthly_history(self, payments_qs, policies_qs, start_date, end_date):
        """Generate monthly historical data."""
        monthly_data = []

        # Iterate through each month in the range
        current_month = start_date.replace(day=1)

        while current_month <= end_date:
            # Calculate month boundaries
            if current_month.month == 12:
                next_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                next_month = current_month.replace(month=current_month.month + 1)

            month_end = next_month - timedelta(days=1)

            # Get payments for this month
            month_payments = payments_qs.filter(
                due_date__gte=current_month, due_date__lte=month_end
            )

            # Get policies created in this month
            month_policies = policies_qs.filter(
                start_date__gte=current_month, start_date__lte=month_end
            )

            # Calculate actual amounts (only paid payments)
            paid_payments = month_payments.filter(paid_date__isnull=False)
            actual_premium = self.calculator.calculate_premium_volume(paid_payments)
            actual_commission = self.calculator.calculate_commission_revenue(
                paid_payments
            )

            # Calculate planned amounts (all payments due in this month)
            planned_premium = self.calculator.calculate_premium_volume(month_payments)
            planned_commission = self.calculator.calculate_commission_revenue(
                month_payments
            )

            # Calculate performance metrics
            payment_discipline = Decimal("0")
            if month_payments.count() > 0:
                payment_discipline = (
                    Decimal(str(paid_payments.count()))
                    / Decimal(str(month_payments.count()))
                ) * Decimal("100")

            # Calculate achievement percentage
            premium_achievement = Decimal("0")
            commission_achievement = Decimal("0")

            if planned_premium > 0:
                premium_achievement = (actual_premium / planned_premium) * Decimal(
                    "100"
                )
            if planned_commission > 0:
                commission_achievement = (
                    actual_commission / planned_commission
                ) * Decimal("100")

            monthly_data.append(
                {
                    "month": current_month,
                    "month_name": calendar.month_name[current_month.month],
                    "year": current_month.year,
                    "actual_premium": actual_premium,
                    "actual_commission": actual_commission,
                    "planned_premium": planned_premium,
                    "planned_commission": planned_commission,
                    "premium_achievement": premium_achievement,
                    "commission_achievement": commission_achievement,
                    "payment_discipline": payment_discipline,
                    "policies_created": month_policies.count(),
                    "total_payments": month_payments.count(),
                    "paid_payments": paid_payments.count(),
                    "overdue_payments": month_payments.filter(
                        paid_date__isnull=True, due_date__lt=datetime.now().date()
                    ).count(),
                }
            )

            # Move to next month
            current_month = next_month

        return monthly_data

    def _calculate_fact_vs_forecast(self, monthly_history, analytics_filter):
        """Calculate fact vs forecast analysis."""
        if not monthly_history:
            return {
                "overall_premium_accuracy": Decimal("0"),
                "overall_commission_accuracy": Decimal("0"),
                "best_month": None,
                "worst_month": None,
                "accuracy_trend": "stable",
            }

        # Calculate overall accuracy
        total_actual_premium = sum(m["actual_premium"] for m in monthly_history)
        total_planned_premium = sum(m["planned_premium"] for m in monthly_history)
        total_actual_commission = sum(m["actual_commission"] for m in monthly_history)
        total_planned_commission = sum(m["planned_commission"] for m in monthly_history)

        overall_premium_accuracy = Decimal("0")
        overall_commission_accuracy = Decimal("0")

        if total_planned_premium > 0:
            overall_premium_accuracy = (
                total_actual_premium / total_planned_premium
            ) * Decimal("100")
        if total_planned_commission > 0:
            overall_commission_accuracy = (
                total_actual_commission / total_planned_commission
            ) * Decimal("100")

        # Find best and worst performing months
        best_month = max(monthly_history, key=lambda x: x["premium_achievement"])
        worst_month = min(monthly_history, key=lambda x: x["premium_achievement"])

        # Calculate accuracy trend
        if len(monthly_history) >= 3:
            recent_accuracy = (
                sum(m["premium_achievement"] for m in monthly_history[-3:]) / 3
            )
            early_accuracy = (
                sum(m["premium_achievement"] for m in monthly_history[:3]) / 3
            )

            if recent_accuracy > early_accuracy + 5:
                accuracy_trend = "improving"
            elif recent_accuracy < early_accuracy - 5:
                accuracy_trend = "declining"
            else:
                accuracy_trend = "stable"
        else:
            accuracy_trend = "insufficient_data"

        return {
            "overall_premium_accuracy": overall_premium_accuracy,
            "overall_commission_accuracy": overall_commission_accuracy,
            "best_month": best_month,
            "worst_month": worst_month,
            "accuracy_trend": accuracy_trend,
            "total_actual_premium": total_actual_premium,
            "total_planned_premium": total_planned_premium,
            "total_actual_commission": total_actual_commission,
            "total_planned_commission": total_planned_commission,
        }

    def _calculate_performance_trends(self, monthly_history):
        """Calculate performance trends over time."""
        if len(monthly_history) < 2:
            return {
                "premium_trend": "insufficient_data",
                "commission_trend": "insufficient_data",
                "policy_trend": "insufficient_data",
                "discipline_trend": "insufficient_data",
                "growth_rate": Decimal("0"),
                "volatility": Decimal("0"),
            }

        # Calculate trends
        premium_values = [float(m["actual_premium"]) for m in monthly_history]
        commission_values = [float(m["actual_commission"]) for m in monthly_history]
        policy_values = [m["policies_created"] for m in monthly_history]
        discipline_values = [float(m["payment_discipline"]) for m in monthly_history]

        def calculate_trend(values):
            if len(values) < 2:
                return "insufficient_data"

            # Simple linear trend calculation
            n = len(values)
            x_sum = sum(range(n))
            y_sum = sum(values)
            xy_sum = sum(i * values[i] for i in range(n))
            x2_sum = sum(i * i for i in range(n))

            if n * x2_sum - x_sum * x_sum == 0:
                return "stable"

            slope = (n * xy_sum - x_sum * y_sum) / (n * x2_sum - x_sum * x_sum)

            if slope > 0.1:
                return "growing"
            elif slope < -0.1:
                return "declining"
            else:
                return "stable"

        # Calculate growth rate (first vs last month)
        first_premium = monthly_history[0]["actual_premium"]
        last_premium = monthly_history[-1]["actual_premium"]

        growth_rate = Decimal("0")
        if first_premium > 0:
            growth_rate = ((last_premium - first_premium) / first_premium) * Decimal(
                "100"
            )

        # Calculate volatility (coefficient of variation)
        import statistics

        volatility = Decimal("0")
        if premium_values and statistics.mean(premium_values) > 0:
            cv = statistics.stdev(premium_values) / statistics.mean(premium_values)
            volatility = Decimal(str(cv * 100))

        return {
            "premium_trend": calculate_trend(premium_values),
            "commission_trend": calculate_trend(commission_values),
            "policy_trend": calculate_trend(policy_values),
            "discipline_trend": calculate_trend(discipline_values),
            "growth_rate": growth_rate,
            "volatility": volatility,
            "best_performing_month": max(
                monthly_history, key=lambda x: x["actual_premium"]
            ),
            "most_stable_month": min(
                monthly_history,
                key=lambda x: abs(
                    float(x["actual_premium"]) - statistics.mean(premium_values)
                ),
            ),
        }

    def _get_monthly_highlights(
        self, payments_qs, policies_qs, start_date, end_date, analytics_filter
    ):
        """Get highlights and key events for each month."""
        from apps.clients.models import Client
        from apps.insurers.models import Branch, Insurer
        from apps.policies.models import InsuranceType
        from django.db.models import Sum, Count

        highlights = []

        # Iterate through each month
        current_month = start_date.replace(day=1)

        while current_month <= end_date:
            # Calculate month boundaries
            if current_month.month == 12:
                next_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                next_month = current_month.replace(month=current_month.month + 1)

            month_end = next_month - timedelta(days=1)

            # Get month data
            month_payments = payments_qs.filter(
                due_date__gte=current_month, due_date__lte=month_end
            )

            month_policies = policies_qs.filter(
                start_date__gte=current_month, start_date__lte=month_end
            )

            paid_month_payments = month_payments.filter(paid_date__isnull=False)

            # Find top client by paid premium
            top_client_data = (
                paid_month_payments.values("policy__client__client_name")
                .annotate(total_premium=Sum("amount"))
                .order_by("-total_premium")
                .first()
            )

            # Find top insurance type
            top_insurance_type = (
                month_policies.values("insurance_type__name")
                .annotate(count=Count("id"))
                .order_by("-count")
                .first()
            )

            # Find largest paid payment for the month
            largest_payment = paid_month_payments.order_by("-amount").first()

            # Calculate month achievements
            month_premium = paid_month_payments.aggregate(total=Sum("amount"))[
                "total"
            ] or Decimal("0")

            highlights.append(
                {
                    "month": current_month,
                    "month_name": calendar.month_name[current_month.month],
                    "top_client": top_client_data["policy__client__client_name"]
                    if top_client_data
                    else "Нет данных",
                    "top_client_premium": top_client_data["total_premium"]
                    if top_client_data
                    else Decimal("0"),
                    "top_insurance_type": top_insurance_type["insurance_type__name"]
                    if top_insurance_type
                    else "Нет данных",
                    "top_insurance_count": top_insurance_type["count"]
                    if top_insurance_type
                    else 0,
                    "largest_policy_sum": largest_payment.amount
                    if largest_payment
                    else Decimal("0"),
                    "largest_policy_client": largest_payment.policy.client.client_name
                    if largest_payment
                    else "Нет данных",
                    "total_premium": month_premium,
                    "policies_count": month_policies.count(),
                }
            )

            current_month = next_month

        return highlights

    def _analyze_problem_areas(self, payments_qs, start_date, end_date):
        """Analyze problem areas and risks."""
        from django.db.models import Sum, Count, Q

        # Get overdue payments in the period
        overdue_payments = payments_qs.filter(
            paid_date__isnull=True, due_date__lt=datetime.now().date()
        )

        # Analyze by month
        monthly_problems = []
        current_month = start_date.replace(day=1)

        while current_month <= end_date:
            if current_month.month == 12:
                next_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                next_month = current_month.replace(month=current_month.month + 1)

            month_end = next_month - timedelta(days=1)

            month_overdue = overdue_payments.filter(
                due_date__gte=current_month, due_date__lte=month_end
            )

            overdue_amount = month_overdue.aggregate(total=Sum("amount"))[
                "total"
            ] or Decimal("0")
            overdue_count = month_overdue.count()

            # Find worst clients for this month
            worst_clients = (
                month_overdue.values("policy__client__client_name")
                .annotate(overdue_amount=Sum("amount"), overdue_count=Count("id"))
                .order_by("-overdue_amount")[:3]
            )

            monthly_problems.append(
                {
                    "month": current_month,
                    "overdue_amount": overdue_amount,
                    "overdue_count": overdue_count,
                    "worst_clients": list(worst_clients),
                }
            )

            current_month = next_month

        # Overall problem analysis
        total_overdue_amount = overdue_payments.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")
        total_overdue_count = overdue_payments.count()

        # Find consistently problematic clients
        problematic_clients = (
            overdue_payments.values("policy__client__client_name")
            .annotate(total_overdue=Sum("amount"), overdue_count=Count("id"))
            .filter(overdue_count__gte=2)
            .order_by("-total_overdue")[:5]
        )

        return {
            "monthly_problems": monthly_problems,
            "total_overdue_amount": total_overdue_amount,
            "total_overdue_count": total_overdue_count,
            "problematic_clients": list(problematic_clients),
            "average_monthly_overdue": total_overdue_amount / len(monthly_problems)
            if monthly_problems
            else Decimal("0"),
        }

    def _calculate_dimensional_breakdown(
        self, payments_qs, policies_qs, analytics_filter
    ):
        """Calculate breakdown by different dimensions."""
        # Branch breakdown (batched)
        branch_policy_count_map = self._build_policy_count_map(policies_qs, "branch_id")
        branch_payment_rows = (
            payments_qs.filter(paid_date__isnull=False)
            .values("policy__branch_id", "policy__branch__branch_name")
            .annotate(
                premium=Coalesce(Sum("amount"), Decimal("0")),
                commission=Coalesce(Sum("kv_rub"), Decimal("0")),
            )
            .order_by("policy__branch__branch_name")
        )
        branch_payment_map = {
            int(row["policy__branch_id"]): {
                "name": row.get("policy__branch__branch_name") or "Не указан филиал",
                "premium": row.get("premium") or Decimal("0"),
                "commission": row.get("commission") or Decimal("0"),
            }
            for row in branch_payment_rows
            if row.get("policy__branch_id") is not None
        }

        branch_breakdown = []
        for branch_id, policy_count in branch_policy_count_map.items():
            payment_data = branch_payment_map.get(
                branch_id,
                {
                    "name": "Не указан филиал",
                    "premium": Decimal("0"),
                    "commission": Decimal("0"),
                },
            )
            branch_breakdown.append(
                {
                    "name": payment_data["name"],
                    "premium": payment_data["premium"],
                    "commission": payment_data["commission"],
                    "policy_count": policy_count,
                }
            )

        # Insurance type breakdown (batched)
        insurance_policy_count_map = self._build_policy_count_map(
            policies_qs, "insurance_type_id"
        )
        insurance_payment_rows = (
            payments_qs.filter(paid_date__isnull=False)
            .values("policy__insurance_type_id", "policy__insurance_type__name")
            .annotate(
                premium=Coalesce(Sum("amount"), Decimal("0")),
                commission=Coalesce(Sum("kv_rub"), Decimal("0")),
            )
            .order_by("policy__insurance_type__name")
        )
        insurance_payment_map = {
            int(row["policy__insurance_type_id"]): {
                "name": row.get("policy__insurance_type__name") or "Не указан вид",
                "premium": row.get("premium") or Decimal("0"),
                "commission": row.get("commission") or Decimal("0"),
            }
            for row in insurance_payment_rows
            if row.get("policy__insurance_type_id") is not None
        }

        insurance_breakdown = []
        for insurance_type_id, policy_count in insurance_policy_count_map.items():
            payment_data = insurance_payment_map.get(
                insurance_type_id,
                {
                    "name": "Не указан вид",
                    "premium": Decimal("0"),
                    "commission": Decimal("0"),
                },
            )
            insurance_breakdown.append(
                {
                    "name": payment_data["name"],
                    "premium": payment_data["premium"],
                    "commission": payment_data["commission"],
                    "policy_count": policy_count,
                }
            )

        # Sort by premium descending
        branch_breakdown.sort(key=lambda x: x["premium"], reverse=True)
        insurance_breakdown.sort(key=lambda x: x["premium"], reverse=True)

        return {
            "branch_breakdown": branch_breakdown,
            "insurance_breakdown": insurance_breakdown,
        }

    def _get_empty_financial_history(self, error=None):
        """Return empty financial history data structure."""
        empty_data = {
            "monthly_history": [],
            "fact_vs_forecast": {
                "overall_premium_accuracy": Decimal("0"),
                "overall_commission_accuracy": Decimal("0"),
                "best_month": None,
                "worst_month": None,
                "accuracy_trend": "insufficient_data",
                "total_actual_premium": Decimal("0"),
                "total_planned_premium": Decimal("0"),
                "total_actual_commission": Decimal("0"),
                "total_planned_commission": Decimal("0"),
            },
            "performance_trends": {
                "premium_trend": "insufficient_data",
                "commission_trend": "insufficient_data",
                "policy_trend": "insufficient_data",
                "discipline_trend": "insufficient_data",
                "growth_rate": Decimal("0"),
                "volatility": Decimal("0"),
            },
            "monthly_highlights": [],
            "problem_analysis": {
                "monthly_problems": [],
                "total_overdue_amount": Decimal("0"),
                "total_overdue_count": 0,
                "problematic_clients": [],
                "average_monthly_overdue": Decimal("0"),
            },
            "dimensional_breakdown": {
                "branch_breakdown": [],
                "insurance_breakdown": [],
            },
            "summary_metrics": {
                "total_actual_premium": Decimal("0"),
                "total_actual_commission": Decimal("0"),
                "total_planned_premium": Decimal("0"),
                "total_planned_commission": Decimal("0"),
                "premium_deviation_amount": Decimal("0"),
                "premium_deviation_percent": Decimal("0"),
                "commission_deviation_amount": Decimal("0"),
                "commission_deviation_percent": Decimal("0"),
                "collection_rate": Decimal("0"),
                "total_payments_count": 0,
                "total_paid_payments": 0,
                "total_overdue_payments": 0,
                "payment_realization_rate": Decimal("0"),
                "average_paid_payment": Decimal("0"),
                "total_policies_created": 0,
                "avg_monthly_premium": Decimal("0"),
                "avg_monthly_commission": Decimal("0"),
                "months_analyzed": 0,
                "period_start": datetime(2026, 1, 1).date(),
                "period_end": datetime.now().date(),
            },
            "filter_applied": False,
        }

        if error:
            empty_data["error"] = error

        return empty_data

    def get_time_series_analytics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get time series analytics with trends and seasonal patterns.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing time series analytics
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from datetime import datetime, timedelta
            from django.db.models import Count, Sum
            from django.db.models.functions import TruncMonth
            from collections import defaultdict
            import calendar

            # Get base querysets
            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            # Apply filters if provided
            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)

            # Determine time range - default to last 2 years
            end_date = datetime.now().date()
            start_date = end_date.replace(year=end_date.year - 2)

            # Override with filter dates if provided
            if analytics_filter and analytics_filter.date_from:
                start_date = analytics_filter.date_from
            if analytics_filter and analytics_filter.date_to:
                end_date = analytics_filter.date_to

            # Filter data to time range
            policies_in_range = policies_qs.filter(
                start_date__gte=start_date, start_date__lte=end_date
            )
            payments_in_range = payments_qs.filter(
                due_date__gte=start_date, due_date__lte=end_date
            )

            # Calculate policy count dynamics by month
            policy_count_by_month = (
                policies_in_range.annotate(month=TruncMonth("start_date"))
                .values("month")
                .annotate(count=Count("id"))
                .order_by("month")
            )

            policy_count_dynamics = []
            for item in policy_count_by_month:
                policy_count_dynamics.append(
                    {
                        "date": item["month"],
                        "value": Decimal(str(item["count"])),
                        "label": item["month"].strftime("%Y-%m"),
                        "additional_data": {"type": "policy_count"},
                    }
                )

            # Calculate premium volume dynamics by month
            premium_by_month = (
                payments_in_range.annotate(month=TruncMonth("due_date"))
                .values("month")
                .annotate(total=Sum("amount"))
                .order_by("month")
            )

            premium_volume_dynamics = []
            for item in premium_by_month:
                premium_volume_dynamics.append(
                    {
                        "date": item["month"],
                        "value": item["total"] or Decimal("0"),
                        "label": item["month"].strftime("%Y-%m"),
                        "additional_data": {"type": "premium_volume"},
                    }
                )

            # Calculate commission revenue dynamics by month
            commission_by_month = (
                payments_in_range.annotate(month=TruncMonth("due_date"))
                .values("month")
                .annotate(total=Sum("kv_rub"))
                .order_by("month")
            )

            commission_revenue_dynamics = []
            for item in commission_by_month:
                commission_revenue_dynamics.append(
                    {
                        "date": item["month"],
                        "value": item["total"] or Decimal("0"),
                        "label": item["month"].strftime("%Y-%m"),
                        "additional_data": {"type": "commission_revenue"},
                    }
                )

            # Calculate seasonal patterns
            monthly_averages = {}
            quarterly_averages = {
                "Q1": Decimal("0"),
                "Q2": Decimal("0"),
                "Q3": Decimal("0"),
                "Q4": Decimal("0"),
            }
            seasonal_indices = {}

            # Group policy counts by month number (1-12)
            monthly_policy_counts = defaultdict(list)
            for item in policy_count_by_month:
                month_num = item["month"].month
                monthly_policy_counts[month_num].append(item["count"])

            # Calculate monthly averages
            for month_num in range(1, 13):
                if month_num in monthly_policy_counts:
                    avg = sum(monthly_policy_counts[month_num]) / len(
                        monthly_policy_counts[month_num]
                    )
                    monthly_averages[month_num] = Decimal(str(avg))
                else:
                    monthly_averages[month_num] = Decimal("0")

            # Calculate quarterly averages
            quarter_counts = defaultdict(list)
            for month_num, counts in monthly_policy_counts.items():
                if month_num in [1, 2, 3]:
                    quarter_counts["Q1"].extend(counts)
                elif month_num in [4, 5, 6]:
                    quarter_counts["Q2"].extend(counts)
                elif month_num in [7, 8, 9]:
                    quarter_counts["Q3"].extend(counts)
                elif month_num in [10, 11, 12]:
                    quarter_counts["Q4"].extend(counts)

            for quarter, counts in quarter_counts.items():
                if counts:
                    quarterly_averages[quarter] = Decimal(
                        str(sum(counts) / len(counts))
                    )

            # Calculate seasonal indices (relative to overall average)
            overall_avg = (
                sum(monthly_averages.values()) / 12
                if monthly_averages
                else Decimal("0")
            )
            for month_num, avg in monthly_averages.items():
                if overall_avg > 0:
                    seasonal_indices[month_num] = avg / overall_avg
                else:
                    seasonal_indices[month_num] = Decimal("1")

            # Find peak and low months
            peak_months = []
            low_months = []
            if monthly_averages:
                max_avg = max(monthly_averages.values())
                min_avg = min(monthly_averages.values())

                for month_num, avg in monthly_averages.items():
                    if avg == max_avg:
                        peak_months.append(month_num)
                    elif avg == min_avg:
                        low_months.append(month_num)

            # Calculate seasonality strength (coefficient of variation)
            if monthly_averages and overall_avg > 0:
                variance = (
                    sum((avg - overall_avg) ** 2 for avg in monthly_averages.values())
                    / 12
                )
                std_dev = variance ** Decimal("0.5")
                seasonality_strength = std_dev / overall_avg
            else:
                seasonality_strength = Decimal("0")

            seasonal_patterns = {
                "monthly_averages": monthly_averages,
                "quarterly_averages": quarterly_averages,
                "seasonal_indices": seasonal_indices,
                "peak_months": peak_months,
                "low_months": low_months,
                "seasonality_strength": seasonality_strength,
            }

            # Calculate branch growth trends
            branch_growth_trends = {}
            branch_monthly_data = (
                policies_in_range.annotate(month=TruncMonth("start_date"))
                .values("branch_id", "branch__branch_name", "month")
                .annotate(count=Count("id"))
                .order_by("branch__branch_name", "month")
            )
            for item in branch_monthly_data:
                branch_name = item.get("branch__branch_name") or "Не указан филиал"
                if branch_name not in branch_growth_trends:
                    branch_growth_trends[branch_name] = []

                branch_growth_trends[branch_name].append(
                    {
                        "date": item["month"],
                        "value": Decimal(str(item["count"])),
                        "label": item["month"].strftime("%Y-%m"),
                        "additional_data": {
                            "branch_id": item.get("branch_id"),
                            "branch_name": branch_name,
                        },
                    }
                )

            # Calculate year-over-year growth rates
            year_over_year_growth = {}
            current_year = end_date.year
            previous_year = current_year - 1

            # Policy count growth
            current_year_policies = policies_qs.filter(
                start_date__year=current_year
            ).count()
            previous_year_policies = policies_qs.filter(
                start_date__year=previous_year
            ).count()

            if previous_year_policies > 0:
                policy_growth = (
                    (current_year_policies - previous_year_policies)
                    / previous_year_policies
                ) * 100
                year_over_year_growth["policy_count"] = Decimal(str(policy_growth))
            else:
                year_over_year_growth["policy_count"] = Decimal("0")

            # Premium volume growth
            current_year_premium = payments_qs.filter(
                due_date__year=current_year
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            previous_year_premium = payments_qs.filter(
                due_date__year=previous_year
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

            if previous_year_premium > 0:
                premium_growth = (
                    (current_year_premium - previous_year_premium)
                    / previous_year_premium
                ) * 100
                year_over_year_growth["premium_volume"] = premium_growth
            else:
                year_over_year_growth["premium_volume"] = Decimal("0")

            # Commission revenue growth
            current_year_commission = payments_qs.filter(
                due_date__year=current_year
            ).aggregate(total=Sum("kv_rub"))["total"] or Decimal("0")
            previous_year_commission = payments_qs.filter(
                due_date__year=previous_year
            ).aggregate(total=Sum("kv_rub"))["total"] or Decimal("0")

            if previous_year_commission > 0:
                commission_growth = (
                    (current_year_commission - previous_year_commission)
                    / previous_year_commission
                ) * 100
                year_over_year_growth["commission_revenue"] = commission_growth
            else:
                year_over_year_growth["commission_revenue"] = Decimal("0")

            return {
                "policy_count_dynamics": policy_count_dynamics,
                "premium_volume_dynamics": premium_volume_dynamics,
                "commission_revenue_dynamics": commission_revenue_dynamics,
                "seasonal_patterns": seasonal_patterns,
                "branch_growth_trends": branch_growth_trends,
                "year_over_year_growth": year_over_year_growth,
                "filter_applied": analytics_filter.has_filters()
                if analytics_filter
                else False,
            }

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error calculating time series analytics: {e}")

            return {
                "policy_count_dynamics": [],
                "premium_volume_dynamics": [],
                "commission_revenue_dynamics": [],
                "seasonal_patterns": {
                    "monthly_averages": {},
                    "quarterly_averages": {},
                    "seasonal_indices": {},
                    "peak_months": [],
                    "low_months": [],
                    "seasonality_strength": Decimal("0"),
                },
                "branch_growth_trends": {},
                "year_over_year_growth": {},
                "filter_applied": False,
                "error": str(e),
            }

    def validate_filter_input(self, filter_data: Dict[str, Any]) -> AnalyticsFilter:
        """
        Validate and create AnalyticsFilter from input data.

        Args:
            filter_data: Dictionary containing filter parameters

        Returns:
            AnalyticsFilter instance

        Raises:
            ValueError: If filter data is invalid
        """
        try:
            # Parse dates
            date_from = None
            date_to = None

            if filter_data.get("date_from"):
                if isinstance(filter_data["date_from"], str):
                    from datetime import datetime

                    date_from = datetime.strptime(
                        filter_data["date_from"], "%Y-%m-%d"
                    ).date()
                else:
                    date_from = filter_data["date_from"]

            if filter_data.get("date_to"):
                if isinstance(filter_data["date_to"], str):
                    from datetime import datetime

                    date_to = datetime.strptime(
                        filter_data["date_to"], "%Y-%m-%d"
                    ).date()
                else:
                    date_to = filter_data["date_to"]

            # Validate date range
            if date_from and date_to and date_from > date_to:
                raise ValueError("Start date cannot be after end date")

            # Parse ID lists
            branch_ids = filter_data.get("branch_ids", [])
            insurer_ids = filter_data.get("insurer_ids", [])
            insurance_type_ids = filter_data.get("insurance_type_ids", [])
            client_ids = filter_data.get("client_ids", [])

            # Ensure IDs are integers
            if branch_ids:
                branch_ids = [int(id) for id in branch_ids]
            if insurer_ids:
                insurer_ids = [int(id) for id in insurer_ids]
            if insurance_type_ids:
                insurance_type_ids = [int(id) for id in insurance_type_ids]
            if client_ids:
                client_ids = [int(id) for id in client_ids]

            # Parse policy_active
            policy_active = filter_data.get("policy_active")
            if policy_active is not None and not isinstance(policy_active, bool):
                policy_active = str(policy_active).lower() in ["true", "1", "yes"]

            # Parse target_month
            target_month = filter_data.get("target_month")
            if target_month == "":
                target_month = None

            return AnalyticsFilter(
                date_from=date_from,
                date_to=date_to,
                branch_ids=branch_ids,
                insurer_ids=insurer_ids,
                insurance_type_ids=insurance_type_ids,
                client_ids=client_ids,
                policy_active=policy_active,
                target_month=target_month,
            )

        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid filter data: {e}")

    def get_dashboard_charts(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get dashboard chart data formatted for visualization.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing formatted chart data for dashboard
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            charts = {}

            # Dashboard charts follow month-based bridge:
            # closed months as actual + current/future as planned
            bridge_branch_metrics = self._get_dashboard_branch_bridge_metrics(
                analytics_filter
            )

            if bridge_branch_metrics:
                premium_data = {
                    metric["branch"]["name"]: metric["bridge_premium"]
                    for metric in bridge_branch_metrics
                }
                charts["premium_by_branch"] = self.chart_provider.get_bar_chart_data(
                    premium_data,
                    title="Итоговый мост премий по филиалам",
                    x_axis_label="Филиалы",
                    y_axis_label="Премии (факт закрытых мес. + план текущий/будущие), руб.",
                )

                market_share_data = {
                    metric["branch"]["name"]: metric["bridge_market_share"]
                    for metric in bridge_branch_metrics
                }
                charts["branch_market_share"] = self.chart_provider.get_pie_chart_data(
                    market_share_data, title="Доля филиалов в итоговом мосте премий (%)"
                )
            else:
                logger.warning("No bridge branch metrics data available for dashboard")

            logger.info(f"Total charts generated: {list(charts.keys())}")
            return charts

        except Exception as e:
            logger.error(f"Error generating dashboard charts: {e}")
            return {}

    def _get_dashboard_branch_bridge_metrics(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> list:
        """
        Build branch metrics for dashboard charts in month-based bridge mode.
        """
        try:
            from apps.policies.models import Policy, PaymentSchedule
            from apps.insurers.models import Branch

            policies_qs = Policy.objects.all()
            payments_qs = PaymentSchedule.objects.all()

            if analytics_filter:
                policies_qs = analytics_filter.apply_to_policies(policies_qs)
                payments_qs = analytics_filter.apply_to_payments(payments_qs)

            (
                closed_months_actual_qs,
                current_and_future_qs,
                _,
            ) = self._split_bridge_payments_by_month_boundary(payments_qs)

            branches_with_data = Branch.objects.filter(
                id__in=policies_qs.values_list("branch_id", flat=True).distinct()
            )

            metrics = []
            total_bridge_premium = Decimal("0")

            for branch in branches_with_data:
                branch_actual_qs = closed_months_actual_qs.filter(policy__branch=branch)
                branch_plan_qs = current_and_future_qs.filter(policy__branch=branch)

                fact_premium = self.calculator.calculate_premium_volume(
                    branch_actual_qs
                )
                plan_premium = self.calculator.calculate_premium_volume(branch_plan_qs)
                bridge_premium = fact_premium + plan_premium

                metrics.append(
                    {
                        "branch": {"id": branch.id, "name": branch.branch_name},
                        "fact_premium": fact_premium,
                        "plan_premium": plan_premium,
                        "bridge_premium": bridge_premium,
                    }
                )
                total_bridge_premium += bridge_premium

            for metric in metrics:
                if total_bridge_premium > 0:
                    metric["bridge_market_share"] = (
                        metric["bridge_premium"] / total_bridge_premium
                    ) * Decimal("100")
                else:
                    metric["bridge_market_share"] = Decimal("0")

            metrics.sort(key=lambda x: x["bridge_premium"], reverse=True)
            return metrics
        except Exception:
            return []

    def get_branch_charts(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get branch analytics chart data formatted for visualization.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing formatted chart data for branch analytics
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            branch_data = self.get_branch_analytics(analytics_filter)
            return self.chart_provider.format_branch_analytics_charts(branch_data)

        except Exception as e:
            logger.error(f"Error generating branch charts: {e}")
            return {}

    def get_insurer_charts(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get insurer analytics chart data formatted for visualization.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing formatted chart data for insurer analytics
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            insurer_data = self.get_insurer_analytics_for_charts(analytics_filter)
            return self.chart_provider.format_insurer_analytics_charts(insurer_data)

        except Exception as e:
            logger.error(f"Error generating insurer charts: {e}")
            return {}

    def get_time_series_charts(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get time series analytics chart data formatted for visualization.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing formatted chart data for time series analytics
        """
        try:
            time_series_data = self.get_time_series_analytics(analytics_filter)
            return self.chart_provider.format_time_series_charts(time_series_data)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error generating time series charts: {e}")
            return {}

    def get_financial_charts(
        self, analytics_filter: Optional[AnalyticsFilter] = None
    ) -> Dict[str, Any]:
        """
        Get financial analytics chart data formatted for visualization.

        Args:
            analytics_filter: Optional filter to apply to the data

        Returns:
            Dictionary containing formatted chart data for financial analytics
        """
        try:
            financial_data = self.get_financial_analytics(analytics_filter)
            return self.chart_provider.format_financial_analytics_charts(financial_data)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error generating financial charts: {e}")
            return {}
