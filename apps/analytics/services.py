"""
Analytics services for calculating business metrics and analytics.
This module contains the core business logic for analytics calculations.
"""

from decimal import Decimal
from datetime import date, datetime
from typing import Optional, Dict, Any
from django.db.models import QuerySet, Sum, Count, Avg
from django.db.models.functions import Coalesce
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

        result = queryset.aggregate(total=Coalesce(Sum("insurance_sum"), Decimal("0")))
        return result["total"]

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
    ):
        self.date_from = date_from
        self.date_to = date_to
        self.branch_ids = branch_ids or []
        self.insurer_ids = insurer_ids or []
        self.insurance_type_ids = insurance_type_ids or []
        self.client_ids = client_ids or []
        self.policy_active = policy_active

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
        )


class AnalyticsService:
    """
    Main analytics service that integrates MetricsCalculator and AnalyticsFilter.
    Provides methods for getting all types of analytics with error handling and validation.
    """

    def __init__(self):
        self.calculator = MetricsCalculator()
        self.chart_provider = ChartDataProvider()

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

            # Calculate metrics
            total_premium_volume = self.calculator.calculate_premium_volume(
                payments_qs, date_range
            )
            total_commission_revenue = self.calculator.calculate_commission_revenue(
                payments_qs, date_range
            )
            total_policy_count = self.calculator.calculate_policy_count(
                policies_qs, date_range
            )
            total_insurance_sum = self.calculator.calculate_insurance_sum(
                payments_qs, date_range
            )
            average_commission_rate = self.calculator.calculate_average_commission_rate(
                payments_qs
            )

            # Count active policies
            active_policies_count = policies_qs.filter(policy_active=True).count()

            return {
                "total_premium_volume": total_premium_volume,
                "total_commission_revenue": total_commission_revenue,
                "total_policy_count": total_policy_count,
                "total_insurance_sum": total_insurance_sum,
                "average_commission_rate": average_commission_rate,
                "active_policies_count": active_policies_count,
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
                "total_premium_volume": Decimal("0"),
                "total_commission_revenue": Decimal("0"),
                "total_policy_count": 0,
                "total_insurance_sum": Decimal("0"),
                "average_commission_rate": Decimal("0"),
                "active_policies_count": 0,
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
            from django.db.models import Count

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

            # Get branches that have policies
            branches_with_data = Branch.objects.filter(
                id__in=policies_qs.values_list("branch_id", flat=True).distinct()
            )

            branch_metrics = []

            for branch in branches_with_data:
                # Filter data for this branch
                branch_policies = policies_qs.filter(branch=branch)
                branch_payments = payments_qs.filter(policy__branch=branch)

                # Calculate metrics for this branch
                premium_volume = self.calculator.calculate_premium_volume(
                    branch_payments, date_range
                )
                commission_revenue = self.calculator.calculate_commission_revenue(
                    branch_payments, date_range
                )
                policy_count = self.calculator.calculate_policy_count(
                    branch_policies, date_range
                )
                insurance_sum = self.calculator.calculate_insurance_sum(
                    branch_payments, date_range
                )

                # Get insurance type distribution for this branch
                insurance_type_distribution = dict(
                    branch_policies.values("insurance_type__name")
                    .annotate(count=Count("id"))
                    .values_list("insurance_type__name", "count")
                )

                # Sort insurance types in preferred order
                insurance_type_distribution = sort_insurance_types(
                    insurance_type_distribution
                )

                branch_metrics.append(
                    {
                        "branch": {"id": branch.id, "name": branch.branch_name},
                        "premium_volume": premium_volume,
                        "commission_revenue": commission_revenue,
                        "policy_count": policy_count,
                        "insurance_sum": insurance_sum,
                        "insurance_type_distribution": insurance_type_distribution,
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
            from django.db.models import Count

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

            # Get insurers that have policies
            insurers_with_data = Insurer.objects.filter(
                id__in=policies_qs.values_list("insurer_id", flat=True).distinct()
            )

            insurer_metrics = []
            total_premium = Decimal("0")
            total_insurance_sum = Decimal("0")

            for insurer in insurers_with_data:
                # Filter data for this insurer
                insurer_policies = policies_qs.filter(insurer=insurer)
                insurer_payments = payments_qs.filter(policy__insurer=insurer)

                # Calculate metrics for this insurer
                premium_volume = self.calculator.calculate_premium_volume(
                    insurer_payments, date_range
                )
                commission_revenue = self.calculator.calculate_commission_revenue(
                    insurer_payments, date_range
                )
                policy_count = self.calculator.calculate_policy_count(
                    insurer_policies, date_range
                )
                insurance_sum = self.calculator.calculate_insurance_sum(
                    insurer_payments, date_range
                )

                total_premium += premium_volume
                total_insurance_sum += insurance_sum

                # Get insurance type distribution for this insurer
                insurance_type_distribution = dict(
                    insurer_policies.values("insurance_type__name")
                    .annotate(count=Count("id"))
                    .values_list("insurance_type__name", "count")
                )

                # Sort insurance types in preferred order
                insurance_type_distribution = sort_insurance_types(
                    insurance_type_distribution
                )

                insurer_metrics.append(
                    {
                        "insurer": insurer,  # Полный объект для страницы аналитики
                        "premium_volume": premium_volume,
                        "commission_revenue": commission_revenue,
                        "policy_count": policy_count,
                        "insurance_sum": insurance_sum,
                        "insurance_type_distribution": insurance_type_distribution,
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
            from apps.policies.models import Policy, PaymentSchedule
            from apps.insurers.models import Insurer
            from django.db.models import Count

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

            # Get insurers that have policies
            insurers_with_data = Insurer.objects.filter(
                id__in=policies_qs.values_list("insurer_id", flat=True).distinct()
            )

            insurer_metrics = []
            total_premium = Decimal("0")
            total_insurance_sum = Decimal("0")

            for insurer in insurers_with_data:
                # Filter data for this insurer
                insurer_policies = policies_qs.filter(insurer=insurer)
                insurer_payments = payments_qs.filter(policy__insurer=insurer)

                # Calculate metrics for this insurer
                premium_volume = self.calculator.calculate_premium_volume(
                    insurer_payments, date_range
                )
                commission_revenue = self.calculator.calculate_commission_revenue(
                    insurer_payments, date_range
                )
                policy_count = self.calculator.calculate_policy_count(
                    insurer_policies, date_range
                )
                insurance_sum = self.calculator.calculate_insurance_sum(
                    insurer_payments, date_range
                )

                total_premium += premium_volume
                total_insurance_sum += insurance_sum

                # Get insurance type distribution for this insurer
                insurance_type_distribution = dict(
                    insurer_policies.values("insurance_type__name")
                    .annotate(count=Count("id"))
                    .values_list("insurance_type__name", "count")
                )

                # Sort insurance types in preferred order
                insurance_type_distribution = sort_insurance_types(
                    insurance_type_distribution
                )

                insurer_metrics.append(
                    {
                        "insurer": {
                            "id": insurer.id,
                            "name": insurer.insurer_name,
                        },  # Упрощенные данные для графиков
                        "premium_volume": premium_volume,
                        "commission_revenue": commission_revenue,
                        "policy_count": policy_count,
                        "insurance_sum": insurance_sum,
                        "insurance_type_distribution": insurance_type_distribution,
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
            logger.error(f"Error calculating insurer analytics for charts: {e}")

            return {
                "insurer_metrics": [],
                "total_insurers": 0,
                "filter_applied": False,
                "error": str(e),
            }

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
            from django.db.models import Count

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

            # Get clients that have policies
            clients_with_data = Client.objects.filter(
                id__in=policies_qs.values_list("client_id", flat=True).distinct()
            )

            client_metrics = []

            for client in clients_with_data:
                # Filter data for this client
                client_policies = policies_qs.filter(client=client)
                client_payments = payments_qs.filter(policy__client=client)

                # Calculate metrics for this client
                premium_volume = self.calculator.calculate_premium_volume(
                    client_payments, date_range
                )
                commission_revenue = self.calculator.calculate_commission_revenue(
                    client_payments, date_range
                )
                policy_count = self.calculator.calculate_policy_count(
                    client_policies, date_range
                )
                insurance_sum = self.calculator.calculate_insurance_sum(
                    client_payments, date_range
                )

                # Calculate average policy value
                if policy_count > 0:
                    average_policy_value = insurance_sum / Decimal(str(policy_count))
                else:
                    average_policy_value = Decimal("0")

                # Get insurance type distribution for this client
                insurance_type_distribution = dict(
                    client_policies.values("insurance_type__name")
                    .annotate(count=Count("id"))
                    .values_list("insurance_type__name", "count")
                )

                # Sort insurance types in preferred order
                insurance_type_distribution = sort_insurance_types(
                    insurance_type_distribution
                )

                # Get branch distribution for this client
                branch_distribution = dict(
                    client_policies.values("branch__branch_name")
                    .annotate(count=Count("id"))
                    .values_list("branch__branch_name", "count")
                )

                # Determine primary branch (branch with most policies)
                primary_branch = None
                if branch_distribution:
                    primary_branch = max(
                        branch_distribution.items(), key=lambda x: x[1]
                    )[0]

                client_metrics.append(
                    {
                        "client": {
                            "id": client.id,
                            "name": client.client_name,
                            "inn": getattr(client, "inn", ""),
                            "contact_person": getattr(client, "contact_person", ""),
                        },
                        "premium_volume": premium_volume,
                        "commission_revenue": commission_revenue,
                        "policy_count": policy_count,
                        "insurance_sum": insurance_sum,
                        "average_policy_value": average_policy_value,
                        "insurance_type_distribution": insurance_type_distribution,
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

            # By insurance type
            from apps.policies.models import InsuranceType

            insurance_types = InsuranceType.objects.filter(
                id__in=policies_qs.values_list(
                    "insurance_type_id", flat=True
                ).distinct()
            )

            for insurance_type in insurance_types:
                type_payments = payments_qs.filter(
                    policy__insurance_type=insurance_type
                )
                avg_rate = self.calculator.calculate_average_commission_rate(
                    type_payments
                )
                average_commission_rates[
                    f"insurance_type_{insurance_type.name}"
                ] = avg_rate

            # By insurer
            from apps.insurers.models import Insurer

            insurers = Insurer.objects.filter(
                id__in=policies_qs.values_list("insurer_id", flat=True).distinct()
            )

            for insurer in insurers:
                insurer_payments = payments_qs.filter(policy__insurer=insurer)
                avg_rate = self.calculator.calculate_average_commission_rate(
                    insurer_payments
                )
                average_commission_rates[f"insurer_{insurer.insurer_name}"] = avg_rate

            # Analyze overdue payments
            overdue_payments_qs = payments_qs.filter(
                paid_date__isnull=True, due_date__lt=today
            )

            # Breakdown by days overdue
            overdue_by_days = {}
            for payment in overdue_payments_qs:
                days_overdue = (today - payment.due_date).days
                if days_overdue <= 30:
                    category = "1-30 days"
                elif days_overdue <= 60:
                    category = "31-60 days"
                elif days_overdue <= 90:
                    category = "61-90 days"
                else:
                    category = "90+ days"

                if category not in overdue_by_days:
                    overdue_by_days[category] = Decimal("0")
                overdue_by_days[category] += payment.amount

            # Breakdown by branch
            overdue_by_branch = {}
            from apps.insurers.models import Branch

            branches = Branch.objects.filter(
                id__in=overdue_payments_qs.values_list(
                    "policy__branch_id", flat=True
                ).distinct()
            )

            for branch in branches:
                branch_overdue = self.calculator.calculate_premium_volume(
                    overdue_payments_qs.filter(policy__branch=branch)
                )
                overdue_by_branch[branch.branch_name] = branch_overdue

            # Breakdown by insurer
            overdue_by_insurer = {}
            for insurer in insurers:
                insurer_overdue = self.calculator.calculate_premium_volume(
                    overdue_payments_qs.filter(policy__insurer=insurer)
                )
                if insurer_overdue > 0:
                    overdue_by_insurer[insurer.insurer_name] = insurer_overdue

            # Calculate average overdue days
            if overdue_payments_qs.exists():
                total_overdue_days = sum(
                    (today - payment.due_date).days for payment in overdue_payments_qs
                )
                average_overdue_days = Decimal(str(total_overdue_days)) / Decimal(
                    str(overdue_payments_qs.count())
                )
            else:
                average_overdue_days = Decimal("0")

            # Find worst performing clients (by overdue amount)
            from apps.clients.models import Client

            worst_performing_clients = []
            clients_with_overdue = Client.objects.filter(
                id__in=overdue_payments_qs.values_list(
                    "policy__client_id", flat=True
                ).distinct()
            )

            for client in clients_with_overdue:
                client_overdue = self.calculator.calculate_premium_volume(
                    overdue_payments_qs.filter(policy__client=client)
                )
                if client_overdue > 0:
                    worst_performing_clients.append(
                        {
                            "client": {
                                "id": client.id,
                                "name": client.client_name,
                                "inn": getattr(client, "inn", ""),
                                "contact_person": getattr(client, "contact_person", ""),
                            },
                            "overdue_amount": client_overdue,
                            "overdue_count": overdue_payments_qs.filter(
                                policy__client=client
                            ).count(),
                        }
                    )

            # Sort by overdue amount (descending)
            worst_performing_clients.sort(
                key=lambda x: x["overdue_amount"], reverse=True
            )
            worst_performing_clients = worst_performing_clients[:10]  # Top 10 worst

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
                "filter_applied": False,
                "error": str(e),
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
            from apps.insurers.models import Branch
            from datetime import datetime, timedelta
            from django.db.models import Count, Sum
            from django.db.models.functions import TruncMonth, TruncYear
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
            branches_with_data = Branch.objects.filter(
                id__in=policies_in_range.values_list("branch_id", flat=True).distinct()
            )

            for branch in branches_with_data:
                branch_policies = policies_in_range.filter(branch=branch)
                branch_monthly_data = (
                    branch_policies.annotate(month=TruncMonth("start_date"))
                    .values("month")
                    .annotate(count=Count("id"))
                    .order_by("month")
                )

                branch_trend = []
                for item in branch_monthly_data:
                    branch_trend.append(
                        {
                            "date": item["month"],
                            "value": Decimal(str(item["count"])),
                            "label": item["month"].strftime("%Y-%m"),
                            "additional_data": {
                                "branch_id": branch.id,
                                "branch_name": branch.branch_name,
                            },
                        }
                    )

                branch_growth_trends[branch.branch_name] = branch_trend

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

            return AnalyticsFilter(
                date_from=date_from,
                date_to=date_to,
                branch_ids=branch_ids,
                insurer_ids=insurer_ids,
                insurance_type_ids=insurance_type_ids,
                client_ids=client_ids,
                policy_active=policy_active,
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
            # Get raw analytics data
            dashboard_data = self.get_dashboard_metrics(analytics_filter)
            branch_data = self.get_branch_analytics(analytics_filter)
            insurer_data = self.get_insurer_analytics_for_charts(analytics_filter)

            charts = {}

            # Format branch charts
            if branch_data.get("branch_metrics"):
                branch_charts = self.chart_provider.format_branch_analytics_charts(
                    branch_data
                )
                charts.update(branch_charts)
                logger.info(f"Added branch charts: {list(branch_charts.keys())}")
            else:
                logger.warning("No branch metrics data available")

            # Format insurer charts
            if insurer_data.get("insurer_metrics"):
                insurer_charts = self.chart_provider.format_insurer_analytics_charts(
                    insurer_data
                )
                charts.update(insurer_charts)
                logger.info(f"Added insurer charts: {list(insurer_charts.keys())}")
            else:
                logger.warning("No insurer metrics data available")

            logger.info(f"Total charts generated: {list(charts.keys())}")
            return charts

        except Exception as e:
            logger.error(f"Error generating dashboard charts: {e}")
            return {}

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
