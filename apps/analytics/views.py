from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.contrib import messages
from datetime import datetime, date
from decimal import Decimal
import logging
import calendar

from .services import AnalyticsService, AnalyticsFilter
from .models import DashboardMetrics
from .exporters import AnalyticsExporter
from apps.insurers.models import Branch, Insurer
from apps.policies.models import InsuranceType
from apps.clients.models import Client
from apps.accounts.mixins import SuperuserRequiredMixin

logger = logging.getLogger(__name__)
security_logger = logging.getLogger("security")


class DashboardView(SuperuserRequiredMixin, TemplateView):
    """
    Main dashboard view displaying key performance indicators.

    Provides overview of business metrics with filtering capabilities.
    Handles both GET requests for page display and POST requests for filtering.
    """

    template_name = "analytics/dashboard.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for dashboard template.

        Returns:
            Dictionary containing dashboard metrics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to analytics dashboard
        security_logger.info(
            f"Analytics dashboard accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get dashboard metrics
            metrics_data = self.analytics_service.get_dashboard_metrics(
                analytics_filter
            )

            # Convert to DashboardMetrics dataclass for better structure
            dashboard_metrics = DashboardMetrics(
                total_premium_volume=metrics_data["total_premium_volume"],
                total_commission_revenue=metrics_data["total_commission_revenue"],
                total_policy_count=metrics_data["total_policy_count"],
                total_insurance_sum=metrics_data["total_insurance_sum"],
                active_policies_count=metrics_data["active_policies_count"],
                average_commission_rate=metrics_data.get("average_commission_rate"),
                filter_applied=metrics_data.get("filter_applied", False),
            )

            # Get chart data
            chart_data = self.analytics_service.get_dashboard_charts(analytics_filter)

            # Format chart data for template
            formatted_chart_data = {}
            for chart_id, chart_info in chart_data.items():
                if hasattr(chart_info, "__dict__"):
                    # Convert dataclass to JSON string for template
                    formatted_chart_data[
                        chart_id
                    ] = self.analytics_service.chart_provider.to_json(chart_info)
                else:
                    formatted_chart_data[chart_id] = chart_info

            # Add filter options for the form
            context.update(
                {
                    "dashboard_metrics": dashboard_metrics,
                    "chart_data": formatted_chart_data,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "current_year": datetime.now().year,
                }
            )

            # Add error message if present
            if "error" in metrics_data:
                messages.error(
                    self.request, f"Ошибка при расчете метрик: {metrics_data['error']}"
                )

        except Exception as e:
            logger.error(f"Error in DashboardView.get_context_data: {e}")
            messages.error(
                self.request, "Произошла ошибка при загрузке данных панели управления"
            )

            # Provide empty metrics as fallback
            context.update(
                {
                    "dashboard_metrics": DashboardMetrics(
                        total_premium_volume=Decimal("0"),
                        total_commission_revenue=Decimal("0"),
                        total_policy_count=0,
                        total_insurance_sum=Decimal("0"),
                        active_policies_count=0,
                        filter_applied=False,
                    ),
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                }
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for filtering dashboard data.

        Returns:
            JsonResponse with updated metrics or error message
        """
        try:
            # Get filter parameters from POST data
            analytics_filter = self._get_analytics_filter_from_post()

            # Get updated metrics
            metrics_data = self.analytics_service.get_dashboard_metrics(
                analytics_filter
            )

            # Get updated chart data
            chart_data = self.analytics_service.get_dashboard_charts(analytics_filter)

            # Format chart data for JSON response
            formatted_charts = {}
            for chart_id, chart_info in chart_data.items():
                if hasattr(chart_info, "__dict__"):
                    # Convert dataclass to dict and then to JSON
                    formatted_charts[
                        chart_id
                    ] = self.analytics_service.chart_provider.to_json(chart_info)
                else:
                    formatted_charts[chart_id] = chart_info

            # Format response data
            response_data = {
                "success": True,
                "metrics": {
                    "total_premium_volume": str(metrics_data["total_premium_volume"]),
                    "total_commission_revenue": str(
                        metrics_data["total_commission_revenue"]
                    ),
                    "total_policy_count": metrics_data["total_policy_count"],
                    "total_insurance_sum": str(metrics_data["total_insurance_sum"]),
                    "active_policies_count": metrics_data["active_policies_count"],
                    "average_commission_rate": str(
                        metrics_data.get("average_commission_rate", "0")
                    ),
                    "filter_applied": metrics_data.get("filter_applied", False),
                },
                "charts": formatted_charts,
            }

            if "error" in metrics_data:
                response_data["warning"] = f"Предупреждение: {metrics_data['error']}"

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error in DashboardView.post: {e}")
            return JsonResponse(
                {"success": False, "error": "Произошла ошибка при применении фильтров"},
                status=500,
            )

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.GET.get("date_from"):
                filter_data["date_from"] = self.request.GET.get("date_from")
            if self.request.GET.get("date_to"):
                filter_data["date_to"] = self.request.GET.get("date_to")

            # Multi-select filters
            if self.request.GET.getlist("branches"):
                filter_data["branch_ids"] = self.request.GET.getlist("branches")
            if self.request.GET.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.GET.getlist("insurers")
            if self.request.GET.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.GET.getlist(
                    "insurance_types"
                )
            if self.request.GET.getlist("clients"):
                filter_data["client_ids"] = self.request.GET.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def _get_analytics_filter_from_post(self):
        """
        Get AnalyticsFilter from POST parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.POST.get("date_from"):
                filter_data["date_from"] = self.request.POST.get("date_from")
            if self.request.POST.get("date_to"):
                filter_data["date_to"] = self.request.POST.get("date_to")

            # Multi-select filters
            if self.request.POST.getlist("branches"):
                filter_data["branch_ids"] = self.request.POST.getlist("branches")
            if self.request.POST.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.POST.getlist("insurers")
            if self.request.POST.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.POST.getlist(
                    "insurance_types"
                )
            if self.request.POST.getlist("clients"):
                filter_data["client_ids"] = self.request.POST.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from POST: {e}")
            raise ValueError(f"Некорректные параметры фильтра: {e}")

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export dashboard metrics to Excel."""
        # Log export access
        security_logger.info(
            f"Dashboard analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get dashboard metrics
            metrics_data = self.analytics_service.get_dashboard_metrics(
                analytics_filter
            )

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_dashboard_metrics(metrics_data, applied_filters)

        except Exception as e:
            logger.error(f"Error exporting dashboard data: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)


class BranchAnalyticsView(SuperuserRequiredMixin, TemplateView):
    """
    Branch analytics view displaying detailed metrics by branch.

    Provides comprehensive analytics for each branch with filtering capabilities
    and detailed drill-down functionality for specific branches.
    """

    template_name = "analytics/branch_analytics.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for branch analytics template.

        Returns:
            Dictionary containing branch analytics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to branch analytics
        security_logger.info(
            f"Branch analytics accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get branch analytics data
            branch_data = self.analytics_service.get_branch_analytics(analytics_filter)

            # Process branch metrics for better template usage
            branch_metrics = branch_data.get("branch_metrics", [])

            # Convert branch dictionaries to Branch objects for template
            for metric in branch_metrics:
                if isinstance(metric.get("branch"), dict):
                    branch_id = metric["branch"].get("id")
                    if branch_id:
                        try:
                            metric["branch"] = Branch.objects.get(id=branch_id)
                        except Branch.DoesNotExist:
                            # Fallback: create a simple object with branch_name
                            class SimpleBranch:
                                def __init__(self, name):
                                    self.branch_name = name

                            metric["branch"] = SimpleBranch(
                                metric["branch"].get("name", "Неизвестный филиал")
                            )

            # Calculate additional metrics for display
            total_premium = sum(metric["premium_volume"] for metric in branch_metrics)
            total_commission = sum(
                metric["commission_revenue"] for metric in branch_metrics
            )
            total_policies = sum(metric["policy_count"] for metric in branch_metrics)

            # Calculate market share for each branch
            for metric in branch_metrics:
                if total_premium > 0:
                    metric["market_share"] = (
                        metric["premium_volume"] / total_premium
                    ) * Decimal("100")
                else:
                    metric["market_share"] = Decimal("0")

            # Sort branches by premium volume (descending)
            branch_metrics.sort(key=lambda x: x["premium_volume"], reverse=True)

            # Find top performing branch
            top_branch = branch_metrics[0] if branch_metrics else None

            # Add filter options for the form
            context.update(
                {
                    "branch_metrics": branch_metrics,
                    "total_branches": branch_data.get("total_branches", 0),
                    "top_performing_branch": top_branch,
                    "policy_status": self.request.GET.get("policy_status", "active"),
                    "total_premium_volume": total_premium,
                    "total_commission_revenue": total_commission,
                    "total_policy_count": total_policies,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "current_year": datetime.now().year,
                }
            )

            # Add error message if present
            if "error" in branch_data:
                messages.error(
                    self.request,
                    f"Ошибка при расчете аналитики филиалов: {branch_data['error']}",
                )

        except Exception as e:
            logger.error(f"Error in BranchAnalyticsView.get_context_data: {e}")
            messages.error(
                self.request, "Произошла ошибка при загрузке аналитики филиалов"
            )

            # Provide empty data as fallback
            context.update(
                {
                    "branch_metrics": [],
                    "total_branches": 0,
                    "top_performing_branch": None,
                    "total_premium_volume": Decimal("0"),
                    "total_commission_revenue": Decimal("0"),
                    "total_policy_count": 0,
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                }
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for filtering branch analytics data.

        Returns:
            JsonResponse with updated branch metrics or error message
        """
        try:
            # Get filter parameters from POST data
            analytics_filter = self._get_analytics_filter_from_post()

            # Get updated branch analytics
            branch_data = self.analytics_service.get_branch_analytics(analytics_filter)

            # Process metrics for JSON response
            branch_metrics = branch_data.get("branch_metrics", [])
            total_premium = sum(metric["premium_volume"] for metric in branch_metrics)

            # Calculate market share and format for JSON
            formatted_metrics = []
            for metric in branch_metrics:
                if total_premium > 0:
                    market_share = (metric["premium_volume"] / total_premium) * Decimal(
                        "100"
                    )
                else:
                    market_share = Decimal("0")

                formatted_metrics.append(
                    {
                        "branch": metric["branch"],
                        "premium_volume": str(metric["premium_volume"]),
                        "commission_revenue": str(metric["commission_revenue"]),
                        "policy_count": metric["policy_count"],
                        "insurance_sum": str(metric["insurance_sum"]),
                        "market_share": str(market_share),
                        "insurance_type_distribution": metric[
                            "insurance_type_distribution"
                        ],
                    }
                )

            # Sort by premium volume
            formatted_metrics.sort(
                key=lambda x: Decimal(x["premium_volume"]), reverse=True
            )

            # Format response data
            response_data = {
                "success": True,
                "branch_metrics": formatted_metrics,
                "total_branches": branch_data.get("total_branches", 0),
                "total_premium_volume": str(
                    sum(metric["premium_volume"] for metric in branch_metrics)
                ),
                "total_commission_revenue": str(
                    sum(metric["commission_revenue"] for metric in branch_metrics)
                ),
                "total_policy_count": sum(
                    metric["policy_count"] for metric in branch_metrics
                ),
                "filter_applied": branch_data.get("filter_applied", False),
            }

            if "error" in branch_data:
                response_data["warning"] = f"Предупреждение: {branch_data['error']}"

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error in BranchAnalyticsView.post: {e}")
            return JsonResponse(
                {"success": False, "error": "Произошла ошибка при применении фильтров"},
                status=500,
            )

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.GET.get("date_from"):
                filter_data["date_from"] = self.request.GET.get("date_from")
            if self.request.GET.get("date_to"):
                filter_data["date_to"] = self.request.GET.get("date_to")

            # Policy status filter - default to "active" for branches
            policy_status = self.request.GET.get("policy_status", "active")
            if policy_status in ["active", "inactive"]:
                filter_data["policy_active"] = policy_status == "active"

            # Multi-select filters
            if self.request.GET.getlist("branches"):
                filter_data["branch_ids"] = self.request.GET.getlist("branches")
            if self.request.GET.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.GET.getlist("insurers")
            if self.request.GET.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.GET.getlist(
                    "insurance_types"
                )
            if self.request.GET.getlist("clients"):
                filter_data["client_ids"] = self.request.GET.getlist("clients")

            # Always create filter if we have policy_status or other data
            if filter_data or policy_status != "all":
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def _get_analytics_filter_from_post(self):
        """
        Get AnalyticsFilter from POST parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.POST.get("date_from"):
                filter_data["date_from"] = self.request.POST.get("date_from")
            if self.request.POST.get("date_to"):
                filter_data["date_to"] = self.request.POST.get("date_to")

            # Multi-select filters
            if self.request.POST.getlist("branches"):
                filter_data["branch_ids"] = self.request.POST.getlist("branches")
            if self.request.POST.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.POST.getlist("insurers")
            if self.request.POST.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.POST.getlist(
                    "insurance_types"
                )
            if self.request.POST.getlist("clients"):
                filter_data["client_ids"] = self.request.POST.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from POST: {e}")
            raise ValueError(f"Некорректные параметры фильтра: {e}")

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export branch analytics to Excel."""
        # Log export access
        security_logger.info(
            f"Branch analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get branch analytics
            branch_data = self.analytics_service.get_branch_analytics(analytics_filter)

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_branch_analytics(branch_data, applied_filters)

        except Exception as e:
            logger.error(f"Error exporting branch analytics: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)


class InsurerAnalyticsView(SuperuserRequiredMixin, TemplateView):
    """
    Insurer analytics view displaying detailed metrics by insurer.

    Provides comprehensive analytics for each insurer with market share analysis,
    filtering capabilities and detailed drill-down functionality for specific insurers.
    """

    template_name = "analytics/insurer_analytics.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for insurer analytics template.

        Returns:
            Dictionary containing insurer analytics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to insurer analytics
        security_logger.info(
            f"Insurer analytics accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get insurer analytics data
            insurer_data = self.analytics_service.get_insurer_analytics(
                analytics_filter
            )

            # Process insurer metrics for better template usage
            insurer_metrics = insurer_data.get("insurer_metrics", [])

            # Calculate additional metrics for display
            total_premium = sum(metric["premium_volume"] for metric in insurer_metrics)
            total_commission = sum(
                metric["commission_revenue"] for metric in insurer_metrics
            )
            total_policies = sum(metric["policy_count"] for metric in insurer_metrics)

            # Market share is already calculated in the service
            # Sort insurers by premium volume (descending)
            insurer_metrics.sort(key=lambda x: x["premium_volume"], reverse=True)

            # Find top performing insurer
            top_insurer = insurer_metrics[0] if insurer_metrics else None

            # Calculate market share distribution for pie chart
            # TOP-10 insurers + Others from real table data
            chart_data_for_pie = {}

            # Take TOP-10 insurers from table
            count = 0
            others_share = 0

            for metric in insurer_metrics:
                market_share = float(metric["market_share"])
                if market_share > 0:
                    if count < 10:  # TOP-10 insurers
                        insurer_name = metric["insurer"].insurer_name
                        chart_data_for_pie[insurer_name] = round(market_share, 1)
                        count += 1
                    else:
                        others_share += market_share

            # Add "Others" for remaining insurers
            if others_share > 0:
                chart_data_for_pie["Другие"] = round(others_share, 1)

            # Debug: log what we're sending to the chart
            logger.info(f"=== TOP-10 + OTHERS ===")
            logger.info(f"Chart data keys: {list(chart_data_for_pie.keys())}")
            logger.info(f"Chart data values: {list(chart_data_for_pie.values())}")
            logger.info(f"Total segments: {len(chart_data_for_pie)}")
            total_chart_percentage = sum(chart_data_for_pie.values())
            logger.info(f"Total percentage: {total_chart_percentage}%")
            logger.info(f"=======================")

            logger.info(f"Chart data for pie: {list(chart_data_for_pie.keys())}")
            logger.info(f"Chart data values: {list(chart_data_for_pie.values())}")
            logger.info(f"Chart segments count: {len(chart_data_for_pie)}")

            # Add filter options for the form
            context.update(
                {
                    "insurer_metrics": insurer_metrics,
                    "total_insurers": insurer_data.get("total_insurers", 0),
                    "top_performing_insurer": top_insurer,
                    "chart_data_for_pie": chart_data_for_pie,
                    "policy_status": self.request.GET.get("policy_status", "active"),
                    "total_premium_volume": total_premium,
                    "total_commission_revenue": total_commission,
                    "total_policy_count": total_policies,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "current_year": datetime.now().year,
                }
            )

            # Add error message if present
            if "error" in insurer_data:
                messages.error(
                    self.request,
                    f"Ошибка при расчете аналитики страховщиков: {insurer_data['error']}",
                )

        except Exception as e:
            logger.error(f"Error in InsurerAnalyticsView.get_context_data: {e}")
            messages.error(
                self.request, "Произошла ошибка при загрузке аналитики страховщиков"
            )

            # Provide empty data as fallback
            context.update(
                {
                    "insurer_metrics": [],
                    "total_insurers": 0,
                    "top_performing_insurer": None,
                    "chart_data_for_pie": {},
                    "total_premium_volume": Decimal("0"),
                    "total_commission_revenue": Decimal("0"),
                    "total_policy_count": 0,
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                }
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for filtering insurer analytics data.

        Returns:
            JsonResponse with updated insurer metrics or error message
        """
        try:
            # Get filter parameters from POST data
            analytics_filter = self._get_analytics_filter_from_post()

            # Get updated insurer analytics
            insurer_data = self.analytics_service.get_insurer_analytics(
                analytics_filter
            )

            # Process metrics for JSON response
            insurer_metrics = insurer_data.get("insurer_metrics", [])

            # Format for JSON response
            formatted_metrics = []
            for metric in insurer_metrics:
                formatted_metrics.append(
                    {
                        "insurer": metric["insurer"],
                        "premium_volume": str(metric["premium_volume"]),
                        "commission_revenue": str(metric["commission_revenue"]),
                        "policy_count": metric["policy_count"],
                        "insurance_sum": str(metric["insurance_sum"]),
                        "market_share": str(metric["market_share"]),
                        "insurance_type_distribution": metric[
                            "insurance_type_distribution"
                        ],
                    }
                )

            # Sort by premium volume
            formatted_metrics.sort(
                key=lambda x: Decimal(x["premium_volume"]), reverse=True
            )

            # Format response data
            response_data = {
                "success": True,
                "insurer_metrics": formatted_metrics,
                "total_insurers": insurer_data.get("total_insurers", 0),
                "total_premium_volume": str(
                    sum(metric["premium_volume"] for metric in insurer_metrics)
                ),
                "total_commission_revenue": str(
                    sum(metric["commission_revenue"] for metric in insurer_metrics)
                ),
                "total_policy_count": sum(
                    metric["policy_count"] for metric in insurer_metrics
                ),
                "filter_applied": insurer_data.get("filter_applied", False),
            }

            if "error" in insurer_data:
                response_data["warning"] = f"Предупреждение: {insurer_data['error']}"

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error in InsurerAnalyticsView.post: {e}")
            return JsonResponse(
                {"success": False, "error": "Произошла ошибка при применении фильтров"},
                status=500,
            )

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.GET.get("date_from"):
                filter_data["date_from"] = self.request.GET.get("date_from")
            if self.request.GET.get("date_to"):
                filter_data["date_to"] = self.request.GET.get("date_to")

            # Policy status filter - default to "active"
            policy_status = self.request.GET.get("policy_status", "active")
            if policy_status in ["active", "inactive"]:
                filter_data["policy_active"] = policy_status == "active"

            # Multi-select filters
            if self.request.GET.getlist("branches"):
                filter_data["branch_ids"] = self.request.GET.getlist("branches")
            if self.request.GET.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.GET.getlist("insurers")
            if self.request.GET.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.GET.getlist(
                    "insurance_types"
                )
            if self.request.GET.getlist("clients"):
                filter_data["client_ids"] = self.request.GET.getlist("clients")

            # Always create filter if we have policy_status or other data
            if filter_data or policy_status != "all":
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def _get_analytics_filter_from_post(self):
        """
        Get AnalyticsFilter from POST parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.POST.get("date_from"):
                filter_data["date_from"] = self.request.POST.get("date_from")
            if self.request.POST.get("date_to"):
                filter_data["date_to"] = self.request.POST.get("date_to")

            # Multi-select filters
            if self.request.POST.getlist("branches"):
                filter_data["branch_ids"] = self.request.POST.getlist("branches")
            if self.request.POST.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.POST.getlist("insurers")
            if self.request.POST.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.POST.getlist(
                    "insurance_types"
                )
            if self.request.POST.getlist("clients"):
                filter_data["client_ids"] = self.request.POST.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from POST: {e}")
            raise ValueError(f"Некорректные параметры фильтра: {e}")

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export insurer analytics to Excel."""
        # Log export access
        security_logger.info(
            f"Insurer analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get insurer analytics
            insurer_data = self.analytics_service.get_insurer_analytics(
                analytics_filter
            )

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_insurer_analytics(insurer_data, applied_filters)

        except Exception as e:
            logger.error(f"Error exporting insurer analytics: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)


class InsuranceTypeAnalyticsView(SuperuserRequiredMixin, TemplateView):
    """
    Insurance type analytics view displaying detailed metrics by insurance type.

    Provides comprehensive product analytics for each insurance type with profitability analysis,
    filtering capabilities and detailed distribution analysis by branches and insurers.
    """

    template_name = "analytics/insurance_type_analytics.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for insurance type analytics template.

        Returns:
            Dictionary containing insurance type analytics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to insurance type analytics
        security_logger.info(
            f"Insurance type analytics accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get insurance type analytics data
            insurance_type_data = self.analytics_service.get_insurance_type_analytics(
                analytics_filter
            )

            # Process insurance type metrics for better template usage
            insurance_type_metrics = insurance_type_data.get(
                "insurance_type_metrics", []
            )

            # Calculate additional metrics for display
            total_premium = sum(
                metric["premium_volume"] for metric in insurance_type_metrics
            )
            total_commission = sum(
                metric["commission_revenue"] for metric in insurance_type_metrics
            )
            total_policies = sum(
                metric["policy_count"] for metric in insurance_type_metrics
            )

            # Calculate profitability ranking
            for metric in insurance_type_metrics:
                if total_premium > 0:
                    metric["premium_share"] = (
                        metric["premium_volume"] / total_premium
                    ) * Decimal("100")
                else:
                    metric["premium_share"] = Decimal("0")

                if total_commission > 0:
                    metric["commission_share"] = (
                        metric["commission_revenue"] / total_commission
                    ) * Decimal("100")
                else:
                    metric["commission_share"] = Decimal("0")

            # Sort insurance types by commission revenue (descending)
            insurance_type_metrics.sort(
                key=lambda x: x["commission_revenue"], reverse=True
            )

            # Find most profitable insurance type
            most_profitable_type = (
                insurance_type_metrics[0] if insurance_type_metrics else None
            )

            # Add filter options for the form
            context.update(
                {
                    "insurance_type_metrics": insurance_type_metrics,
                    "total_insurance_types": insurance_type_data.get(
                        "total_insurance_types", 0
                    ),
                    "most_profitable_type": most_profitable_type,
                    "total_premium_volume": total_premium,
                    "total_commission_revenue": total_commission,
                    "total_policy_count": total_policies,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "current_year": datetime.now().year,
                }
            )

            # Add error message if present
            if "error" in insurance_type_data:
                messages.error(
                    self.request,
                    f"Ошибка при расчете аналитики видов страхования: {insurance_type_data['error']}",
                )

        except Exception as e:
            logger.error(f"Error in InsuranceTypeAnalyticsView.get_context_data: {e}")
            messages.error(
                self.request,
                "Произошла ошибка при загрузке аналитики видов страхования",
            )

            # Provide empty data as fallback
            context.update(
                {
                    "insurance_type_metrics": [],
                    "total_insurance_types": 0,
                    "most_profitable_type": None,
                    "total_premium_volume": Decimal("0"),
                    "total_commission_revenue": Decimal("0"),
                    "total_policy_count": 0,
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                }
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for filtering insurance type analytics data.

        Returns:
            JsonResponse with updated insurance type metrics or error message
        """
        try:
            # Get filter parameters from POST data
            analytics_filter = self._get_analytics_filter_from_post()

            # Get updated insurance type analytics
            insurance_type_data = self.analytics_service.get_insurance_type_analytics(
                analytics_filter
            )

            # Process metrics for JSON response
            insurance_type_metrics = insurance_type_data.get(
                "insurance_type_metrics", []
            )
            total_premium = sum(
                metric["premium_volume"] for metric in insurance_type_metrics
            )
            total_commission = sum(
                metric["commission_revenue"] for metric in insurance_type_metrics
            )

            # Format for JSON response
            formatted_metrics = []
            for metric in insurance_type_metrics:
                if total_premium > 0:
                    premium_share = (
                        metric["premium_volume"] / total_premium
                    ) * Decimal("100")
                else:
                    premium_share = Decimal("0")

                if total_commission > 0:
                    commission_share = (
                        metric["commission_revenue"] / total_commission
                    ) * Decimal("100")
                else:
                    commission_share = Decimal("0")

                formatted_metrics.append(
                    {
                        "insurance_type": metric["insurance_type"],
                        "premium_volume": str(metric["premium_volume"]),
                        "commission_revenue": str(metric["commission_revenue"]),
                        "policy_count": metric["policy_count"],
                        "insurance_sum": str(metric["insurance_sum"]),
                        "average_commission_per_policy": str(
                            metric["average_commission_per_policy"]
                        ),
                        "premium_share": str(premium_share),
                        "commission_share": str(commission_share),
                        "branch_distribution": metric["branch_distribution"],
                        "insurer_distribution": metric["insurer_distribution"],
                    }
                )

            # Sort by commission revenue
            formatted_metrics.sort(
                key=lambda x: Decimal(x["commission_revenue"]), reverse=True
            )

            # Format response data
            response_data = {
                "success": True,
                "insurance_type_metrics": formatted_metrics,
                "total_insurance_types": insurance_type_data.get(
                    "total_insurance_types", 0
                ),
                "total_premium_volume": str(
                    sum(metric["premium_volume"] for metric in insurance_type_metrics)
                ),
                "total_commission_revenue": str(
                    sum(
                        metric["commission_revenue"]
                        for metric in insurance_type_metrics
                    )
                ),
                "total_policy_count": sum(
                    metric["policy_count"] for metric in insurance_type_metrics
                ),
                "filter_applied": insurance_type_data.get("filter_applied", False),
            }

            if "error" in insurance_type_data:
                response_data[
                    "warning"
                ] = f"Предупреждение: {insurance_type_data['error']}"

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error in InsuranceTypeAnalyticsView.post: {e}")
            return JsonResponse(
                {"success": False, "error": "Произошла ошибка при применении фильтров"},
                status=500,
            )

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.GET.get("date_from"):
                filter_data["date_from"] = self.request.GET.get("date_from")
            if self.request.GET.get("date_to"):
                filter_data["date_to"] = self.request.GET.get("date_to")

            # Multi-select filters
            if self.request.GET.getlist("branches"):
                filter_data["branch_ids"] = self.request.GET.getlist("branches")
            if self.request.GET.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.GET.getlist("insurers")
            if self.request.GET.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.GET.getlist(
                    "insurance_types"
                )
            if self.request.GET.getlist("clients"):
                filter_data["client_ids"] = self.request.GET.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def _get_analytics_filter_from_post(self):
        """
        Get AnalyticsFilter from POST parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.POST.get("date_from"):
                filter_data["date_from"] = self.request.POST.get("date_from")
            if self.request.POST.get("date_to"):
                filter_data["date_to"] = self.request.POST.get("date_to")

            # Multi-select filters
            if self.request.POST.getlist("branches"):
                filter_data["branch_ids"] = self.request.POST.getlist("branches")
            if self.request.POST.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.POST.getlist("insurers")
            if self.request.POST.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.POST.getlist(
                    "insurance_types"
                )
            if self.request.POST.getlist("clients"):
                filter_data["client_ids"] = self.request.POST.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from POST: {e}")
            raise ValueError(f"Некорректные параметры фильтра: {e}")

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export insurance type analytics to Excel."""
        # Log export access
        security_logger.info(
            f"Insurance type analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get insurance type analytics
            insurance_type_data = self.analytics_service.get_insurance_type_analytics(
                analytics_filter
            )

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_insurance_type_analytics(
                insurance_type_data, applied_filters
            )

        except Exception as e:
            logger.error(f"Error exporting insurance type analytics: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)


class ClientAnalyticsView(SuperuserRequiredMixin, TemplateView):
    """
    Client analytics view displaying detailed metrics by client.

    Provides comprehensive client analytics with rankings, top lists by various criteria,
    filtering capabilities and detailed distribution analysis by branches and insurance types.
    """

    template_name = "analytics/client_analytics.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for client analytics template.

        Returns:
            Dictionary containing client analytics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to client analytics
        security_logger.info(
            f"Client analytics accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get client analytics data
            client_data = self.analytics_service.get_client_analytics(analytics_filter)

            # Process client metrics for better template usage
            top_clients_by_insurance_sum = client_data.get(
                "top_clients_by_insurance_sum", []
            )
            top_clients_by_premium = client_data.get("top_clients_by_premium", [])
            top_clients_by_commission = client_data.get("top_clients_by_commission", [])
            top_clients_by_policy_count = client_data.get(
                "top_clients_by_policy_count", []
            )

            # Calculate additional metrics for display
            total_clients = client_data.get("total_clients", 0)

            # Get distribution data
            client_distribution_by_branch = client_data.get(
                "client_distribution_by_branch", {}
            )
            client_distribution_by_insurance_type = client_data.get(
                "client_distribution_by_insurance_type", {}
            )

            # Calculate totals from all clients, not just top lists
            all_client_metrics = client_data.get("all_client_metrics", [])

            total_premium_volume = sum(
                client["premium_volume"] for client in all_client_metrics
            )
            total_commission_revenue = sum(
                client["commission_revenue"] for client in all_client_metrics
            )
            total_policy_count = sum(
                client["policy_count"] for client in all_client_metrics
            )

            # Add percentage calculations for top clients
            for client in top_clients_by_insurance_sum:
                if total_premium_volume > 0:
                    client["insurance_sum_percentage"] = (
                        client["insurance_sum"]
                        / sum(c["insurance_sum"] for c in top_clients_by_insurance_sum)
                    ) * Decimal("100")
                else:
                    client["insurance_sum_percentage"] = Decimal("0")

            for client in top_clients_by_commission:
                if total_commission_revenue > 0:
                    client["commission_percentage"] = (
                        client["commission_revenue"] / total_commission_revenue
                    ) * Decimal("100")
                else:
                    client["commission_percentage"] = Decimal("0")

            for client in top_clients_by_policy_count:
                if total_policy_count > 0:
                    client["policy_count_percentage"] = (
                        Decimal(str(client["policy_count"]))
                        / Decimal(str(total_policy_count))
                    ) * Decimal("100")
                else:
                    client["policy_count_percentage"] = Decimal("0")

            # Add filter options for the form
            context.update(
                {
                    "top_clients_by_insurance_sum": top_clients_by_insurance_sum,
                    "top_clients_by_premium": top_clients_by_premium,
                    "top_clients_by_commission": top_clients_by_commission,
                    "top_clients_by_policy_count": top_clients_by_policy_count,
                    "client_distribution_by_branch": client_distribution_by_branch,
                    "client_distribution_by_insurance_type": client_distribution_by_insurance_type,
                    "total_clients": total_clients,
                    "total_premium_volume": total_premium_volume,
                    "total_commission_revenue": total_commission_revenue,
                    "total_policy_count": total_policy_count,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "policy_status": self.request.GET.get("policy_status", "active"),
                    "current_year": datetime.now().year,
                }
            )

            # Add error message if present
            if "error" in client_data:
                messages.error(
                    self.request,
                    f"Ошибка при расчете аналитики клиентов: {client_data['error']}",
                )

        except Exception as e:
            logger.error(f"Error in ClientAnalyticsView.get_context_data: {e}")
            messages.error(
                self.request, "Произошла ошибка при загрузке аналитики клиентов"
            )

            # Provide empty data as fallback
            context.update(
                {
                    "top_clients_by_insurance_sum": [],
                    "top_clients_by_premium": [],
                    "top_clients_by_commission": [],
                    "top_clients_by_policy_count": [],
                    "client_distribution_by_branch": {},
                    "client_distribution_by_insurance_type": {},
                    "total_clients": 0,
                    "total_premium_volume": Decimal("0"),
                    "total_commission_revenue": Decimal("0"),
                    "total_policy_count": 0,
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                }
            )

        return context

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Policy status filter - default to "active" for clients
            policy_status = self.request.GET.get("policy_status", "active")
            if policy_status in ["active", "inactive"]:
                filter_data["policy_active"] = policy_status == "active"

            # Always create filter if we have policy_status or other data
            if filter_data or policy_status != "all":
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export client analytics to Excel."""
        # Log export access
        security_logger.info(
            f"Client analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get client analytics
            client_data = self.analytics_service.get_client_analytics(analytics_filter)

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_client_analytics(client_data, applied_filters)

        except Exception as e:
            logger.error(f"Error exporting client analytics: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)


class FinancialAnalyticsView(SuperuserRequiredMixin, TemplateView):
    """
    Financial analytics view displaying forecasting and payment analysis.

    Provides comprehensive financial analytics with premium and commission forecasting,
    payment status analysis, overdue payment tracking, and average commission rates
    by various dimensions.
    """

    template_name = "analytics/financial_analytics.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for financial analytics template.

        Returns:
            Dictionary containing financial analytics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to financial analytics
        security_logger.info(
            f"Financial analytics accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get financial analytics data
            financial_data = self.analytics_service.get_financial_analytics(
                analytics_filter
            )

            # Process financial metrics for better template usage
            monthly_premium_forecast = financial_data.get(
                "monthly_premium_forecast", []
            )
            monthly_commission_forecast = financial_data.get(
                "monthly_commission_forecast", []
            )
            payment_status_analysis = financial_data.get("payment_status_analysis", {})

            # Calculate summary metrics
            total_forecasted_premium = sum(
                forecast["forecasted_premium"] for forecast in monthly_premium_forecast
            )
            total_forecasted_commission = sum(
                forecast["forecasted_commission"]
                for forecast in monthly_commission_forecast
            )

            # Calculate actual vs forecasted for completed months
            actual_vs_forecast_variance = []
            for forecast in monthly_premium_forecast:
                if forecast["actual_premium"] is not None:
                    variance = (
                        forecast["actual_premium"] - forecast["forecasted_premium"]
                    )
                    variance_percentage = Decimal("0")
                    if forecast["forecasted_premium"] > 0:
                        variance_percentage = (
                            variance / forecast["forecasted_premium"]
                        ) * Decimal("100")

                    actual_vs_forecast_variance.append(
                        {
                            "month": forecast["month"],
                            "variance": variance,
                            "variance_percentage": variance_percentage,
                            "forecasted": forecast["forecasted_premium"],
                            "actual": forecast["actual_premium"],
                        }
                    )

            # Prepare chart data for forecasts
            forecast_chart_labels = [
                forecast["month"].strftime("%Y-%m")
                for forecast in monthly_premium_forecast
            ]
            premium_forecast_data = [
                float(forecast["forecasted_premium"])
                for forecast in monthly_premium_forecast
            ]
            commission_forecast_data = [
                float(forecast["forecasted_commission"])
                for forecast in monthly_commission_forecast
            ]

            # Prepare payment status chart data
            payment_status_labels = ["Оплачено", "Ожидает оплаты", "Просрочено"]
            payment_status_counts = [
                payment_status_analysis.get("paid_payments", 0),
                payment_status_analysis.get("pending_payments", 0),
                payment_status_analysis.get("overdue_payments", 0),
            ]
            payment_status_amounts = [
                float(payment_status_analysis.get("paid_amount", Decimal("0"))),
                float(payment_status_analysis.get("pending_amount", Decimal("0"))),
                float(payment_status_analysis.get("overdue_amount", Decimal("0"))),
            ]

            # Add filter options for the form
            context.update(
                {
                    "monthly_premium_forecast": monthly_premium_forecast,
                    "monthly_commission_forecast": monthly_commission_forecast,
                    "payment_status_analysis": payment_status_analysis,
                    "total_forecasted_premium": total_forecasted_premium,
                    "total_forecasted_commission": total_forecasted_commission,
                    "actual_vs_forecast_variance": actual_vs_forecast_variance,
                    "forecast_chart_labels": forecast_chart_labels,
                    "premium_forecast_data": premium_forecast_data,
                    "commission_forecast_data": commission_forecast_data,
                    "payment_status_labels": payment_status_labels,
                    "payment_status_counts": payment_status_counts,
                    "payment_status_amounts": payment_status_amounts,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "current_year": datetime.now().year,
                }
            )

            # Add error message if present
            if "error" in financial_data:
                messages.error(
                    self.request,
                    f"Ошибка при расчете финансовой аналитики: {financial_data['error']}",
                )

        except Exception as e:
            logger.error(f"Error in FinancialAnalyticsView.get_context_data: {e}")
            messages.error(
                self.request, "Произошла ошибка при загрузке финансовой аналитики"
            )

            # Provide empty data as fallback
            context.update(
                {
                    "monthly_premium_forecast": [],
                    "monthly_commission_forecast": [],
                    "payment_status_analysis": {},
                    "total_forecasted_premium": Decimal("0"),
                    "total_forecasted_commission": Decimal("0"),
                    "actual_vs_forecast_variance": [],
                    "forecast_chart_labels": [],
                    "premium_forecast_data": [],
                    "commission_forecast_data": [],
                    "payment_status_labels": [],
                    "payment_status_counts": [],
                    "payment_status_amounts": [],
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                }
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for filtering financial analytics data.

        Returns:
            JsonResponse with updated financial metrics or error message
        """
        try:
            # Get filter parameters from POST data
            analytics_filter = self._get_analytics_filter_from_post()

            # Get updated financial analytics
            financial_data = self.analytics_service.get_financial_analytics(
                analytics_filter
            )

            # Process metrics for JSON response
            monthly_premium_forecast = financial_data.get(
                "monthly_premium_forecast", []
            )
            monthly_commission_forecast = financial_data.get(
                "monthly_commission_forecast", []
            )

            # Format forecasts for JSON
            formatted_premium_forecast = []
            for forecast in monthly_premium_forecast:
                formatted_premium_forecast.append(
                    {
                        "month": forecast["month"].strftime("%Y-%m-%d"),
                        "forecasted_premium": str(forecast["forecasted_premium"]),
                        "forecasted_commission": str(forecast["forecasted_commission"]),
                        "actual_premium": str(forecast["actual_premium"])
                        if forecast["actual_premium"]
                        else None,
                        "actual_commission": str(forecast["actual_commission"])
                        if forecast["actual_commission"]
                        else None,
                        "confidence_level": str(forecast["confidence_level"]),
                    }
                )

            formatted_commission_forecast = []
            for forecast in monthly_commission_forecast:
                formatted_commission_forecast.append(
                    {
                        "month": forecast["month"].strftime("%Y-%m-%d"),
                        "forecasted_premium": str(forecast["forecasted_premium"]),
                        "forecasted_commission": str(forecast["forecasted_commission"]),
                        "actual_premium": str(forecast["actual_premium"])
                        if forecast["actual_premium"]
                        else None,
                        "actual_commission": str(forecast["actual_commission"])
                        if forecast["actual_commission"]
                        else None,
                        "confidence_level": str(forecast["confidence_level"]),
                    }
                )

            # Format payment status analysis
            payment_status_analysis = financial_data.get("payment_status_analysis", {})
            formatted_payment_status = {
                "total_payments": payment_status_analysis.get("total_payments", 0),
                "paid_payments": payment_status_analysis.get("paid_payments", 0),
                "pending_payments": payment_status_analysis.get("pending_payments", 0),
                "overdue_payments": payment_status_analysis.get("overdue_payments", 0),
                "paid_amount": str(
                    payment_status_analysis.get("paid_amount", Decimal("0"))
                ),
                "pending_amount": str(
                    payment_status_analysis.get("pending_amount", Decimal("0"))
                ),
                "overdue_amount": str(
                    payment_status_analysis.get("overdue_amount", Decimal("0"))
                ),
                "payment_discipline_rate": str(
                    payment_status_analysis.get("payment_discipline_rate", Decimal("0"))
                ),
            }

            # Format response data
            response_data = {
                "success": True,
                "monthly_premium_forecast": formatted_premium_forecast,
                "monthly_commission_forecast": formatted_commission_forecast,
                "payment_status_analysis": formatted_payment_status,
                "filter_applied": financial_data.get("filter_applied", False),
            }

            if "error" in financial_data:
                response_data["warning"] = f"Предупреждение: {financial_data['error']}"

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error in FinancialAnalyticsView.post: {e}")
            return JsonResponse(
                {"success": False, "error": "Произошла ошибка при применении фильтров"},
                status=500,
            )

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.GET.get("date_from"):
                filter_data["date_from"] = self.request.GET.get("date_from")
            if self.request.GET.get("date_to"):
                filter_data["date_to"] = self.request.GET.get("date_to")

            # Multi-select filters
            if self.request.GET.getlist("branches"):
                filter_data["branch_ids"] = self.request.GET.getlist("branches")
            if self.request.GET.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.GET.getlist("insurers")
            if self.request.GET.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.GET.getlist(
                    "insurance_types"
                )
            if self.request.GET.getlist("clients"):
                filter_data["client_ids"] = self.request.GET.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def _get_analytics_filter_from_post(self):
        """
        Get AnalyticsFilter from POST parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.POST.get("date_from"):
                filter_data["date_from"] = self.request.POST.get("date_from")
            if self.request.POST.get("date_to"):
                filter_data["date_to"] = self.request.POST.get("date_to")

            # Multi-select filters
            if self.request.POST.getlist("branches"):
                filter_data["branch_ids"] = self.request.POST.getlist("branches")
            if self.request.POST.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.POST.getlist("insurers")
            if self.request.POST.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.POST.getlist(
                    "insurance_types"
                )
            if self.request.POST.getlist("clients"):
                filter_data["client_ids"] = self.request.POST.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from POST: {e}")
            raise ValueError(f"Некорректные параметры фильтра: {e}")

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export financial analytics to Excel."""
        # Log export access
        security_logger.info(
            f"Financial analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get financial analytics
            financial_data = self.analytics_service.get_financial_analytics(
                analytics_filter
            )

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_financial_analytics(
                financial_data, applied_filters
            )

        except Exception as e:
            logger.error(f"Error exporting financial analytics: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)


class TimeSeriesAnalyticsView(SuperuserRequiredMixin, TemplateView):
    """
    Time series analytics view displaying trends and seasonal patterns.

    Provides comprehensive time series analytics with policy count dynamics,
    premium volume trends, commission revenue trends, seasonal pattern analysis,
    and branch growth trends over time.
    """

    template_name = "analytics/time_series_analytics.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.analytics_service = AnalyticsService()
        self.exporter = AnalyticsExporter()

    def get_context_data(self, **kwargs):
        """
        Get context data for time series analytics template.

        Returns:
            Dictionary containing time series analytics and filter options
        """
        context = super().get_context_data(**kwargs)

        # Log access to time series analytics
        security_logger.info(
            f"Time series analytics accessed by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get filter parameters from request
            analytics_filter = self._get_analytics_filter()

            # Get time series analytics data
            time_series_data = self.analytics_service.get_time_series_analytics(
                analytics_filter
            )

            # Process time series metrics for better template usage
            policy_count_dynamics = time_series_data.get("policy_count_dynamics", [])
            premium_volume_dynamics = time_series_data.get(
                "premium_volume_dynamics", []
            )
            commission_revenue_dynamics = time_series_data.get(
                "commission_revenue_dynamics", []
            )
            seasonal_patterns = time_series_data.get("seasonal_patterns", {})
            branch_growth_trends = time_series_data.get("branch_growth_trends", {})
            year_over_year_growth = time_series_data.get("year_over_year_growth", {})

            # Prepare chart data for policy count dynamics
            policy_chart_labels = [point["label"] for point in policy_count_dynamics]
            policy_chart_data = [
                float(point["value"]) for point in policy_count_dynamics
            ]

            # Prepare chart data for premium volume dynamics
            premium_chart_labels = [point["label"] for point in premium_volume_dynamics]
            premium_chart_data = [
                float(point["value"]) for point in premium_volume_dynamics
            ]

            # Prepare chart data for commission revenue dynamics
            commission_chart_labels = [
                point["label"] for point in commission_revenue_dynamics
            ]
            commission_chart_data = [
                float(point["value"]) for point in commission_revenue_dynamics
            ]

            # Prepare seasonal patterns chart data
            monthly_averages = seasonal_patterns.get("monthly_averages", {})
            seasonal_chart_labels = [
                calendar.month_name[month] for month in range(1, 13)
            ]
            seasonal_chart_data = [
                float(monthly_averages.get(month, 0)) for month in range(1, 13)
            ]

            # Prepare quarterly data
            quarterly_averages = seasonal_patterns.get("quarterly_averages", {})
            quarterly_chart_labels = ["Q1", "Q2", "Q3", "Q4"]
            quarterly_chart_data = [
                float(quarterly_averages.get(q, 0)) for q in quarterly_chart_labels
            ]

            # Prepare branch growth trends chart data
            branch_trends_chart_data = {}
            for branch_name, trend_data in branch_growth_trends.items():
                branch_trends_chart_data[branch_name] = {
                    "labels": [point["label"] for point in trend_data],
                    "data": [float(point["value"]) for point in trend_data],
                }

            # Calculate summary statistics
            total_periods = len(policy_count_dynamics)

            # Calculate growth rates for the displayed period
            period_growth_rates = {}
            if policy_count_dynamics and len(policy_count_dynamics) > 1:
                first_period = policy_count_dynamics[0]["value"]
                last_period = policy_count_dynamics[-1]["value"]
                if first_period > 0:
                    policy_period_growth = (
                        (last_period - first_period) / first_period
                    ) * 100
                    period_growth_rates["policy_count"] = policy_period_growth
                else:
                    period_growth_rates["policy_count"] = Decimal("0")

            if premium_volume_dynamics and len(premium_volume_dynamics) > 1:
                first_period = premium_volume_dynamics[0]["value"]
                last_period = premium_volume_dynamics[-1]["value"]
                if first_period > 0:
                    premium_period_growth = (
                        (last_period - first_period) / first_period
                    ) * 100
                    period_growth_rates["premium_volume"] = premium_period_growth
                else:
                    period_growth_rates["premium_volume"] = Decimal("0")

            if commission_revenue_dynamics and len(commission_revenue_dynamics) > 1:
                first_period = commission_revenue_dynamics[0]["value"]
                last_period = commission_revenue_dynamics[-1]["value"]
                if first_period > 0:
                    commission_period_growth = (
                        (last_period - first_period) / first_period
                    ) * 100
                    period_growth_rates["commission_revenue"] = commission_period_growth
                else:
                    period_growth_rates["commission_revenue"] = Decimal("0")

            # Get peak and low months names
            peak_months = seasonal_patterns.get("peak_months", [])
            low_months = seasonal_patterns.get("low_months", [])
            peak_month_names = [calendar.month_name[month] for month in peak_months]
            low_month_names = [calendar.month_name[month] for month in low_months]

            # Add filter options for the form
            context.update(
                {
                    "policy_count_dynamics": policy_count_dynamics,
                    "premium_volume_dynamics": premium_volume_dynamics,
                    "commission_revenue_dynamics": commission_revenue_dynamics,
                    "seasonal_patterns": seasonal_patterns,
                    "branch_growth_trends": branch_growth_trends,
                    "year_over_year_growth": year_over_year_growth,
                    "period_growth_rates": period_growth_rates,
                    "total_periods": total_periods,
                    "peak_month_names": peak_month_names,
                    "low_month_names": low_month_names,
                    "policy_chart_labels": policy_chart_labels,
                    "policy_chart_data": policy_chart_data,
                    "premium_chart_labels": premium_chart_labels,
                    "premium_chart_data": premium_chart_data,
                    "commission_chart_labels": commission_chart_labels,
                    "commission_chart_data": commission_chart_data,
                    "seasonal_chart_labels": seasonal_chart_labels,
                    "seasonal_chart_data": seasonal_chart_data,
                    "quarterly_chart_labels": quarterly_chart_labels,
                    "quarterly_chart_data": quarterly_chart_data,
                    "branch_trends_chart_data": branch_trends_chart_data,
                    "branches": Branch.objects.all().order_by("branch_name"),
                    "insurers": Insurer.objects.all().order_by("insurer_name"),
                    "insurance_types": InsuranceType.objects.all().order_by("name"),
                    "clients": Client.objects.all().order_by("client_name")[
                        :100
                    ],  # Limit for performance
                    "current_filter": analytics_filter,
                    "filter_applied": analytics_filter.has_filters()
                    if analytics_filter
                    else False,
                    "current_year": datetime.now().year,
                    "time_range_display": self._get_time_range_display(
                        analytics_filter
                    ),
                }
            )

            # Add error message if present
            if "error" in time_series_data:
                messages.error(
                    self.request,
                    f"Ошибка при расчете временной аналитики: {time_series_data['error']}",
                )

        except Exception as e:
            logger.error(f"Error in TimeSeriesAnalyticsView.get_context_data: {e}")
            messages.error(
                self.request, "Произошла ошибка при загрузке временной аналитики"
            )

            # Provide empty data as fallback
            context.update(
                {
                    "policy_count_dynamics": [],
                    "premium_volume_dynamics": [],
                    "commission_revenue_dynamics": [],
                    "seasonal_patterns": {},
                    "branch_growth_trends": {},
                    "year_over_year_growth": {},
                    "period_growth_rates": {},
                    "total_periods": 0,
                    "peak_month_names": [],
                    "low_month_names": [],
                    "policy_chart_labels": [],
                    "policy_chart_data": [],
                    "premium_chart_labels": [],
                    "premium_chart_data": [],
                    "commission_chart_labels": [],
                    "commission_chart_data": [],
                    "seasonal_chart_labels": [],
                    "seasonal_chart_data": [],
                    "quarterly_chart_labels": [],
                    "quarterly_chart_data": [],
                    "branch_trends_chart_data": {},
                    "branches": Branch.objects.none(),
                    "insurers": Insurer.objects.none(),
                    "insurance_types": InsuranceType.objects.none(),
                    "clients": Client.objects.none(),
                    "current_filter": None,
                    "filter_applied": False,
                    "current_year": datetime.now().year,
                    "time_range_display": self._get_time_range_display(None),
                }
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for filtering time series analytics data.

        Returns:
            JsonResponse with updated time series metrics or error message
        """
        try:
            # Get filter parameters from POST data
            analytics_filter = self._get_analytics_filter_from_post()

            # Get updated time series analytics
            time_series_data = self.analytics_service.get_time_series_analytics(
                analytics_filter
            )

            # Process metrics for JSON response
            policy_count_dynamics = time_series_data.get("policy_count_dynamics", [])
            premium_volume_dynamics = time_series_data.get(
                "premium_volume_dynamics", []
            )
            commission_revenue_dynamics = time_series_data.get(
                "commission_revenue_dynamics", []
            )

            # Format dynamics for JSON
            formatted_policy_dynamics = []
            for point in policy_count_dynamics:
                formatted_policy_dynamics.append(
                    {
                        "date": point["date"].strftime("%Y-%m-%d"),
                        "value": str(point["value"]),
                        "label": point["label"],
                        "additional_data": point.get("additional_data", {}),
                    }
                )

            formatted_premium_dynamics = []
            for point in premium_volume_dynamics:
                formatted_premium_dynamics.append(
                    {
                        "date": point["date"].strftime("%Y-%m-%d"),
                        "value": str(point["value"]),
                        "label": point["label"],
                        "additional_data": point.get("additional_data", {}),
                    }
                )

            formatted_commission_dynamics = []
            for point in commission_revenue_dynamics:
                formatted_commission_dynamics.append(
                    {
                        "date": point["date"].strftime("%Y-%m-%d"),
                        "value": str(point["value"]),
                        "label": point["label"],
                        "additional_data": point.get("additional_data", {}),
                    }
                )

            # Format seasonal patterns
            seasonal_patterns = time_series_data.get("seasonal_patterns", {})
            formatted_seasonal_patterns = {
                "monthly_averages": {
                    str(k): str(v)
                    for k, v in seasonal_patterns.get("monthly_averages", {}).items()
                },
                "quarterly_averages": {
                    k: str(v)
                    for k, v in seasonal_patterns.get("quarterly_averages", {}).items()
                },
                "seasonal_indices": {
                    str(k): str(v)
                    for k, v in seasonal_patterns.get("seasonal_indices", {}).items()
                },
                "peak_months": seasonal_patterns.get("peak_months", []),
                "low_months": seasonal_patterns.get("low_months", []),
                "seasonality_strength": str(
                    seasonal_patterns.get("seasonality_strength", Decimal("0"))
                ),
            }

            # Format branch growth trends
            branch_growth_trends = time_series_data.get("branch_growth_trends", {})
            formatted_branch_trends = {}
            for branch_name, trend_data in branch_growth_trends.items():
                formatted_trend = []
                for point in trend_data:
                    formatted_trend.append(
                        {
                            "date": point["date"].strftime("%Y-%m-%d"),
                            "value": str(point["value"]),
                            "label": point["label"],
                            "additional_data": point.get("additional_data", {}),
                        }
                    )
                formatted_branch_trends[branch_name] = formatted_trend

            # Format year-over-year growth
            year_over_year_growth = time_series_data.get("year_over_year_growth", {})
            formatted_yoy_growth = {k: str(v) for k, v in year_over_year_growth.items()}

            # Format response data
            response_data = {
                "success": True,
                "policy_count_dynamics": formatted_policy_dynamics,
                "premium_volume_dynamics": formatted_premium_dynamics,
                "commission_revenue_dynamics": formatted_commission_dynamics,
                "seasonal_patterns": formatted_seasonal_patterns,
                "branch_growth_trends": formatted_branch_trends,
                "year_over_year_growth": formatted_yoy_growth,
                "filter_applied": time_series_data.get("filter_applied", False),
            }

            if "error" in time_series_data:
                response_data[
                    "warning"
                ] = f"Предупреждение: {time_series_data['error']}"

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error in TimeSeriesAnalyticsView.post: {e}")
            return JsonResponse(
                {"success": False, "error": "Произошла ошибка при применении фильтров"},
                status=500,
            )

    def _get_analytics_filter(self):
        """
        Get AnalyticsFilter from GET parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.GET.get("date_from"):
                filter_data["date_from"] = self.request.GET.get("date_from")
            if self.request.GET.get("date_to"):
                filter_data["date_to"] = self.request.GET.get("date_to")

            # Multi-select filters
            if self.request.GET.getlist("branches"):
                filter_data["branch_ids"] = self.request.GET.getlist("branches")
            if self.request.GET.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.GET.getlist("insurers")
            if self.request.GET.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.GET.getlist(
                    "insurance_types"
                )
            if self.request.GET.getlist("clients"):
                filter_data["client_ids"] = self.request.GET.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from GET: {e}")
            return None

    def _get_analytics_filter_from_post(self):
        """
        Get AnalyticsFilter from POST parameters.

        Returns:
            AnalyticsFilter instance or None if no filters applied
        """
        try:
            filter_data = {}

            # Date filters
            if self.request.POST.get("date_from"):
                filter_data["date_from"] = self.request.POST.get("date_from")
            if self.request.POST.get("date_to"):
                filter_data["date_to"] = self.request.POST.get("date_to")

            # Multi-select filters
            if self.request.POST.getlist("branches"):
                filter_data["branch_ids"] = self.request.POST.getlist("branches")
            if self.request.POST.getlist("insurers"):
                filter_data["insurer_ids"] = self.request.POST.getlist("insurers")
            if self.request.POST.getlist("insurance_types"):
                filter_data["insurance_type_ids"] = self.request.POST.getlist(
                    "insurance_types"
                )
            if self.request.POST.getlist("clients"):
                filter_data["client_ids"] = self.request.POST.getlist("clients")

            if filter_data:
                return self.analytics_service.validate_filter_input(filter_data)

            return None

        except Exception as e:
            logger.error(f"Error creating analytics filter from POST: {e}")
            raise ValueError(f"Некорректные параметры фильтра: {e}")

    def get(self, request, *args, **kwargs):
        """Handle GET requests including export requests."""
        if request.GET.get("export") == "excel":
            return self.export_data()
        return super().get(request, *args, **kwargs)

    def export_data(self):
        """Export time series analytics to Excel."""
        # Log export access
        security_logger.info(
            f"Time series analytics export by user {self.request.user.username} "
            f"from IP {self.request.META.get('REMOTE_ADDR', 'unknown')}"
        )

        try:
            # Get current filter
            analytics_filter = self._get_analytics_filter()

            # Get time series analytics
            time_series_data = self.analytics_service.get_time_series_analytics(
                analytics_filter
            )

            # Prepare applied filters info for export
            applied_filters = {}
            if analytics_filter:
                if analytics_filter.date_from:
                    applied_filters["Date From"] = analytics_filter.date_from.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.date_to:
                    applied_filters["Date To"] = analytics_filter.date_to.strftime(
                        "%Y-%m-%d"
                    )
                if analytics_filter.branch_ids:
                    branch_names = Branch.objects.filter(
                        id__in=analytics_filter.branch_ids
                    ).values_list("branch_name", flat=True)
                    applied_filters["Branches"] = ", ".join(branch_names)
                if analytics_filter.insurer_ids:
                    insurer_names = Insurer.objects.filter(
                        id__in=analytics_filter.insurer_ids
                    ).values_list("insurer_name", flat=True)
                    applied_filters["Insurers"] = ", ".join(insurer_names)
                if analytics_filter.insurance_type_ids:
                    type_names = InsuranceType.objects.filter(
                        id__in=analytics_filter.insurance_type_ids
                    ).values_list("name", flat=True)
                    applied_filters["Insurance Types"] = ", ".join(type_names)

            # Export data
            return self.exporter.export_time_series_analytics(
                time_series_data, applied_filters
            )

        except Exception as e:
            logger.error(f"Error exporting time series analytics: {e}")
            messages.error(self.request, "Произошла ошибка при экспорте данных")
            return self.get(self.request)

    def _get_time_range_display(self, analytics_filter):
        """
        Get display string for the current time range.

        Args:
            analytics_filter: AnalyticsFilter instance

        Returns:
            String describing the time range
        """
        if analytics_filter and analytics_filter.date_from and analytics_filter.date_to:
            return f"{analytics_filter.date_from.strftime('%d.%m.%Y')} - {analytics_filter.date_to.strftime('%d.%m.%Y')}"
        elif analytics_filter and analytics_filter.date_from:
            return f"с {analytics_filter.date_from.strftime('%d.%m.%Y')}"
        elif analytics_filter and analytics_filter.date_to:
            return f"до {analytics_filter.date_to.strftime('%d.%m.%Y')}"
        else:
            # Default to last 2 years
            end_date = datetime.now().date()
            start_date = date(end_date.year - 1, end_date.month, end_date.day)
            return (
                f"{start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"
            )
