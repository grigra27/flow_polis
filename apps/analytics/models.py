"""
Analytics data models and DTO classes.
This module contains dataclass models for analytical data transfer objects.
"""

from dataclasses import dataclass
from decimal import Decimal
from datetime import date
from typing import List, Dict, Optional, Any
from apps.insurers.models import Branch, Insurer
from apps.clients.models import Client


@dataclass
class DashboardMetrics:
    """
    Main dashboard metrics containing key performance indicators.

    Attributes:
        total_premium_volume: Total premium volume across all policies
        total_commission_revenue: Total commission revenue earned
        total_policy_count: Total number of policies
        total_insurance_sum: Total insurance sum of all policies
        active_policies_count: Number of currently active policies
        current_year_growth: Growth percentage compared to previous year
        average_commission_rate: Average commission rate percentage
        filter_applied: Whether any filters are currently applied
    """

    total_premium_volume: Decimal
    total_commission_revenue: Decimal
    total_policy_count: int
    total_insurance_sum: Decimal
    active_policies_count: int
    current_year_growth: Optional[Decimal] = None
    average_commission_rate: Optional[Decimal] = None
    filter_applied: bool = False


@dataclass
class BranchMetric:
    """
    Metrics for a single branch.

    Attributes:
        branch: Branch object containing branch information
        premium_volume: Total premium volume for this branch
        commission_revenue: Total commission revenue for this branch
        policy_count: Number of policies for this branch
        insurance_sum: Total insurance sum for this branch
        insurance_type_distribution: Distribution of policies by insurance type
        market_share: Branch's market share as percentage
    """

    branch: Dict[str, Any]  # Branch info as dict to avoid model dependencies
    premium_volume: Decimal
    commission_revenue: Decimal
    policy_count: int
    insurance_sum: Decimal
    insurance_type_distribution: Dict[str, int]
    market_share: Optional[Decimal] = None


@dataclass
class BranchAnalytics:
    """
    Complete analytics data for branches.

    Attributes:
        branch_metrics: List of metrics for each branch
        total_branches: Total number of branches with data
        top_performing_branch: Branch with highest performance
        filter_applied: Whether any filters are currently applied
    """

    branch_metrics: List[BranchMetric]
    total_branches: int
    top_performing_branch: Optional[BranchMetric] = None
    filter_applied: bool = False


@dataclass
class InsurerMetric:
    """
    Metrics for a single insurer.

    Attributes:
        insurer: Insurer object containing insurer information
        premium_volume: Total premium volume for this insurer
        commission_revenue: Total commission revenue for this insurer
        policy_count: Number of policies for this insurer
        insurance_sum: Total insurance sum for this insurer
        insurance_type_distribution: Distribution of policies by insurance type
        market_share: Insurer's market share as percentage
    """

    insurer: Dict[str, Any]  # Insurer info as dict to avoid model dependencies
    premium_volume: Decimal
    commission_revenue: Decimal
    policy_count: int
    insurance_sum: Decimal
    insurance_type_distribution: Dict[str, int]
    market_share: Optional[Decimal] = None


@dataclass
class InsurerAnalytics:
    """
    Complete analytics data for insurers.

    Attributes:
        insurer_metrics: List of metrics for each insurer
        total_insurers: Total number of insurers with data
        market_share_distribution: Overall market share distribution
        top_performing_insurer: Insurer with highest performance
        filter_applied: Whether any filters are currently applied
    """

    insurer_metrics: List[InsurerMetric]
    total_insurers: int
    market_share_distribution: Dict[str, Decimal]
    top_performing_insurer: Optional[InsurerMetric] = None
    filter_applied: bool = False


@dataclass
class InsuranceTypeMetric:
    """
    Metrics for a single insurance type.

    Attributes:
        insurance_type: Insurance type information
        premium_volume: Total premium volume for this insurance type
        commission_revenue: Total commission revenue for this insurance type
        policy_count: Number of policies for this insurance type
        insurance_sum: Total insurance sum for this insurance type
        average_commission_per_policy: Average commission per policy
        branch_distribution: Distribution of policies by branch
        insurer_distribution: Distribution of policies by insurer
    """

    insurance_type: Dict[str, Any]  # Insurance type info as dict
    premium_volume: Decimal
    commission_revenue: Decimal
    policy_count: int
    insurance_sum: Decimal
    average_commission_per_policy: Decimal
    branch_distribution: Dict[str, int]
    insurer_distribution: Dict[str, int]


@dataclass
class InsuranceTypeAnalytics:
    """
    Complete analytics data for insurance types.

    Attributes:
        insurance_type_metrics: List of metrics for each insurance type
        total_insurance_types: Total number of insurance types with data
        most_profitable_type: Insurance type with highest profitability
        filter_applied: Whether any filters are currently applied
    """

    insurance_type_metrics: List[InsuranceTypeMetric]
    total_insurance_types: int
    most_profitable_type: Optional[InsuranceTypeMetric] = None
    filter_applied: bool = False


@dataclass
class ClientMetric:
    """
    Metrics for a single client.

    Attributes:
        client: Client object containing client information
        premium_volume: Total premium volume for this client
        commission_revenue: Total commission revenue for this client
        policy_count: Number of policies for this client
        insurance_sum: Total insurance sum for this client
        average_policy_value: Average policy value for this client
        insurance_type_distribution: Distribution of policies by insurance type
        branch_distribution: Distribution of policies by branch
    """

    client: Dict[str, Any]  # Client info as dict to avoid model dependencies
    premium_volume: Decimal
    commission_revenue: Decimal
    policy_count: int
    insurance_sum: Decimal
    average_policy_value: Decimal
    insurance_type_distribution: Dict[str, int]
    branch_distribution: Dict[str, int]


@dataclass
class ClientAnalytics:
    """
    Complete analytics data for clients.

    Attributes:
        top_clients_by_insurance_sum: Top clients ranked by insurance sum
        top_clients_by_commission: Top clients ranked by commission revenue
        top_clients_by_policy_count: Top clients ranked by policy count
        client_distribution_by_branch: Distribution of clients by branch
        client_distribution_by_insurance_type: Distribution of clients by insurance type
        total_clients: Total number of clients with data
        filter_applied: Whether any filters are currently applied
    """

    top_clients_by_insurance_sum: List[ClientMetric]
    top_clients_by_commission: List[ClientMetric]
    top_clients_by_policy_count: List[ClientMetric]
    client_distribution_by_branch: Dict[str, int]
    client_distribution_by_insurance_type: Dict[str, int]
    total_clients: int
    filter_applied: bool = False


@dataclass
class MonthlyForecast:
    """
    Monthly forecast data point.

    Attributes:
        month: Month as date (first day of month)
        forecasted_premium: Forecasted premium volume for the month
        forecasted_commission: Forecasted commission revenue for the month
        actual_premium: Actual premium volume (if available)
        actual_commission: Actual commission revenue (if available)
        confidence_level: Confidence level of the forecast (0-100)
    """

    month: date
    forecasted_premium: Decimal
    forecasted_commission: Decimal
    actual_premium: Optional[Decimal] = None
    actual_commission: Optional[Decimal] = None
    confidence_level: Optional[Decimal] = None


@dataclass
class PaymentStatusAnalysis:
    """
    Analysis of payment statuses.

    Attributes:
        total_payments: Total number of payments
        paid_payments: Number of paid payments
        pending_payments: Number of pending payments
        overdue_payments: Number of overdue payments
        paid_amount: Total amount of paid payments
        pending_amount: Total amount of pending payments
        overdue_amount: Total amount of overdue payments
        payment_discipline_rate: Payment discipline rate as percentage
    """

    total_payments: int
    paid_payments: int
    pending_payments: int
    overdue_payments: int
    paid_amount: Decimal
    pending_amount: Decimal
    overdue_amount: Decimal
    payment_discipline_rate: Decimal


@dataclass
class OverdueAnalysis:
    """
    Analysis of overdue payments.

    Attributes:
        total_overdue_amount: Total amount of overdue payments
        overdue_by_days: Breakdown of overdue amounts by days overdue
        overdue_by_branch: Breakdown of overdue amounts by branch
        overdue_by_insurer: Breakdown of overdue amounts by insurer
        average_overdue_days: Average number of days overdue
        worst_performing_clients: Clients with highest overdue amounts
    """

    total_overdue_amount: Decimal
    overdue_by_days: Dict[str, Decimal]  # e.g., "1-30 days": amount
    overdue_by_branch: Dict[str, Decimal]
    overdue_by_insurer: Dict[str, Decimal]
    average_overdue_days: Decimal
    worst_performing_clients: List[ClientMetric]


@dataclass
class FinancialAnalytics:
    """
    Complete financial analytics data.

    Attributes:
        monthly_premium_forecast: Monthly premium forecasts
        monthly_commission_forecast: Monthly commission forecasts
        payment_status_analysis: Analysis of payment statuses
        average_commission_rates: Average commission rates by dimension
        overdue_payments_analysis: Analysis of overdue payments
        cash_flow_projection: Cash flow projections
        filter_applied: Whether any filters are currently applied
    """

    monthly_premium_forecast: List[MonthlyForecast]
    monthly_commission_forecast: List[MonthlyForecast]
    payment_status_analysis: PaymentStatusAnalysis
    average_commission_rates: Dict[str, Decimal]
    overdue_payments_analysis: OverdueAnalysis
    cash_flow_projection: Optional[List[MonthlyForecast]] = None
    filter_applied: bool = False


@dataclass
class TimePoint:
    """
    Time series data point.

    Attributes:
        date: Date of the data point
        value: Numeric value for the data point
        label: Human-readable label for the data point
        additional_data: Additional metadata for the data point
    """

    date: date
    value: Decimal
    label: str
    additional_data: Optional[Dict[str, Any]] = None


@dataclass
class SeasonalPatterns:
    """
    Seasonal pattern analysis.

    Attributes:
        monthly_averages: Average values by month (1-12)
        quarterly_averages: Average values by quarter (Q1-Q4)
        seasonal_indices: Seasonal indices showing relative performance
        peak_months: Months with highest activity
        low_months: Months with lowest activity
        seasonality_strength: Strength of seasonal pattern (0-1)
    """

    monthly_averages: Dict[int, Decimal]  # month number -> average value
    quarterly_averages: Dict[str, Decimal]  # "Q1", "Q2", etc. -> average value
    seasonal_indices: Dict[int, Decimal]  # month number -> seasonal index
    peak_months: List[int]  # month numbers
    low_months: List[int]  # month numbers
    seasonality_strength: Decimal


@dataclass
class TimeSeriesAnalytics:
    """
    Complete time series analytics data.

    Attributes:
        policy_count_dynamics: Time series of policy count changes
        premium_volume_dynamics: Time series of premium volume changes
        commission_revenue_dynamics: Time series of commission revenue changes
        seasonal_patterns: Seasonal pattern analysis
        branch_growth_trends: Growth trends by branch
        year_over_year_growth: Year-over-year growth rates
        filter_applied: Whether any filters are currently applied
    """

    policy_count_dynamics: List[TimePoint]
    premium_volume_dynamics: List[TimePoint]
    commission_revenue_dynamics: List[TimePoint]
    seasonal_patterns: SeasonalPatterns
    branch_growth_trends: Dict[str, List[TimePoint]]
    year_over_year_growth: Optional[Dict[str, Decimal]] = None
    filter_applied: bool = False


# Chart data models for visualization


@dataclass
class PieChartData:
    """
    Data structure for pie charts.

    Attributes:
        labels: List of labels for pie slices
        values: List of values corresponding to labels
        colors: Optional list of colors for slices
        title: Chart title
    """

    labels: List[str]
    values: List[Decimal]
    colors: Optional[List[str]] = None
    title: str = ""


@dataclass
class BarChartData:
    """
    Data structure for bar charts.

    Attributes:
        labels: List of labels for bars
        datasets: List of datasets, each containing values and metadata
        title: Chart title
        x_axis_label: Label for X axis
        y_axis_label: Label for Y axis
    """

    labels: List[str]
    datasets: List[
        Dict[str, Any]
    ]  # Each dataset has 'label', 'data', 'backgroundColor', etc.
    title: str = ""
    x_axis_label: str = ""
    y_axis_label: str = ""


@dataclass
class LineChartData:
    """
    Data structure for line charts.

    Attributes:
        labels: List of labels for X axis
        datasets: List of datasets, each containing values and metadata
        title: Chart title
        x_axis_label: Label for X axis
        y_axis_label: Label for Y axis
    """

    labels: List[str]
    datasets: List[
        Dict[str, Any]
    ]  # Each dataset has 'label', 'data', 'borderColor', etc.
    title: str = ""
    x_axis_label: str = ""
    y_axis_label: str = ""


@dataclass
class TimeSeriesChartData:
    """
    Data structure for time series charts.

    Attributes:
        time_points: List of time points with dates and values
        datasets: List of datasets for multiple series
        title: Chart title
        date_format: Format for displaying dates
        value_format: Format for displaying values
    """

    time_points: List[TimePoint]
    datasets: List[Dict[str, Any]]
    title: str = ""
    date_format: str = "%Y-%m-%d"
    value_format: str = ",.2f"


# Export data models


@dataclass
class ExportData:
    """
    Base class for export data.

    Attributes:
        filename: Suggested filename for export
        headers: List of column headers
        rows: List of data rows
        metadata: Additional metadata for export
    """

    filename: str
    headers: List[str]
    rows: List[List[Any]]
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class DashboardExportData(ExportData):
    """Export data for dashboard metrics."""

    pass


@dataclass
class BranchExportData(ExportData):
    """Export data for branch analytics."""

    pass


@dataclass
class InsurerExportData(ExportData):
    """Export data for insurer analytics."""

    pass


@dataclass
class ClientExportData(ExportData):
    """Export data for client analytics."""

    pass


@dataclass
class FinancialExportData(ExportData):
    """Export data for financial analytics."""

    pass


@dataclass
class TimeSeriesExportData(ExportData):
    """Export data for time series analytics."""

    pass
