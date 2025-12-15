"""
Chart data providers for analytics visualization.
This module contains providers that format analytics data for Chart.js visualization.
"""

from typing import Dict, List, Any, Optional, Union
from decimal import Decimal
from datetime import date, datetime
from dataclasses import dataclass
import json


@dataclass
class ChartDataPoint:
    """Single data point for charts."""

    label: str
    value: Union[Decimal, int, float]
    color: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None


@dataclass
class PieChartData:
    """Data structure for pie charts."""

    labels: List[str]
    data: List[Union[Decimal, int, float]]
    colors: List[str]
    title: str
    total: Union[Decimal, int, float]
    type: str = "pie"


@dataclass
class BarChartData:
    """Data structure for bar charts."""

    labels: List[str]
    datasets: List[Dict[str, Any]]
    title: str
    x_axis_label: str
    y_axis_label: str
    type: str = "bar"


@dataclass
class LineChartData:
    """Data structure for line charts."""

    labels: List[str]
    datasets: List[Dict[str, Any]]
    title: str
    x_axis_label: str
    y_axis_label: str
    type: str = "line"


@dataclass
class TimeSeriesData:
    """Data structure for time series charts."""

    datasets: List[Dict[str, Any]]
    title: str
    x_axis_label: str
    y_axis_label: str
    time_unit: str  # 'month', 'quarter', 'year'
    type: str = "timeseries"


class ChartDataProvider:
    """
    Provider for formatting analytics data into Chart.js compatible formats.
    Handles different chart types and provides consistent data formatting.
    """

    # Default color palettes for different chart types
    DEFAULT_PIE_COLORS = [
        "#FF6384",
        "#36A2EB",
        "#FFCE56",
        "#4BC0C0",
        "#9966FF",
        "#FF9F40",
        "#FF6384",
        "#C9CBCF",
        "#4BC0C0",
        "#FF6384",
    ]

    DEFAULT_BAR_COLORS = [
        "#36A2EB",
        "#FF6384",
        "#FFCE56",
        "#4BC0C0",
        "#9966FF",
        "#FF9F40",
        "#FF6384",
        "#C9CBCF",
        "#4BC0C0",
        "#FF6384",
    ]

    DEFAULT_LINE_COLORS = ["#36A2EB", "#FF6384", "#FFCE56", "#4BC0C0", "#9966FF"]

    def get_pie_chart_data(
        self,
        data: Dict[str, Union[Decimal, int, float]],
        title: str = "Распределение",
        colors: Optional[List[str]] = None,
    ) -> PieChartData:
        """
        Format data for pie chart visualization.

        Args:
            data: Dictionary with labels as keys and values as data
            title: Chart title
            colors: Optional custom colors list

        Returns:
            PieChartData object formatted for Chart.js
        """
        if not data:
            return PieChartData(labels=[], data=[], colors=[], title=title, total=0)

        # Sort data by value (descending)
        sorted_items = sorted(data.items(), key=lambda x: float(x[1]), reverse=True)

        labels = [item[0] for item in sorted_items]
        values = [float(item[1]) for item in sorted_items]

        # Use provided colors or default palette
        if colors is None:
            colors = self.DEFAULT_PIE_COLORS[: len(labels)]
        else:
            # Extend colors if needed
            while len(colors) < len(labels):
                colors.extend(self.DEFAULT_PIE_COLORS)
            colors = colors[: len(labels)]

        total = sum(values)

        return PieChartData(
            labels=labels, data=values, colors=colors, title=title, total=total
        )

    def get_bar_chart_data(
        self,
        data: Dict[
            str,
            Union[
                Dict[str, Union[Decimal, int, float]], List[Union[Decimal, int, float]]
            ],
        ],
        title: str = "Сравнение",
        x_axis_label: str = "Категории",
        y_axis_label: str = "Значения",
        colors: Optional[List[str]] = None,
    ) -> BarChartData:
        """
        Format data for bar chart visualization.

        Args:
            data: Dictionary with categories as keys and values/datasets as data
            title: Chart title
            x_axis_label: X-axis label
            y_axis_label: Y-axis label
            colors: Optional custom colors list

        Returns:
            BarChartData object formatted for Chart.js
        """
        if not data:
            return BarChartData(
                labels=[],
                datasets=[],
                title=title,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
            )

        # Handle different data formats
        if isinstance(list(data.values())[0], dict):
            # Multiple datasets format: {category: {dataset1: value1, dataset2: value2}}
            labels = list(data.keys())
            dataset_names = set()

            # Collect all dataset names
            for category_data in data.values():
                dataset_names.update(category_data.keys())

            dataset_names = sorted(list(dataset_names))
            datasets = []

            # Use provided colors or default palette
            if colors is None:
                colors = self.DEFAULT_BAR_COLORS[:]
                # Extend colors if needed
                while len(colors) < len(dataset_names):
                    colors.extend(self.DEFAULT_BAR_COLORS)
                colors = colors[: len(dataset_names)]
            else:
                # Extend colors if needed
                while len(colors) < len(dataset_names):
                    colors.extend(self.DEFAULT_BAR_COLORS)
                colors = colors[: len(dataset_names)]

            for i, dataset_name in enumerate(dataset_names):
                dataset_values = []
                for label in labels:
                    value = data[label].get(dataset_name, 0)
                    dataset_values.append(float(value))

                datasets.append(
                    {
                        "label": dataset_name,
                        "data": dataset_values,
                        "backgroundColor": colors[i],
                        "borderColor": colors[i],
                        "borderWidth": 1,
                    }
                )

        else:
            # Single dataset format: {category: value}
            labels = list(data.keys())
            values = [float(value) for value in data.values()]

            # Use provided colors or default palette
            if colors is None:
                colors = self.DEFAULT_BAR_COLORS[:]
                # Extend colors if needed
                while len(colors) < len(labels):
                    colors.extend(self.DEFAULT_BAR_COLORS)
                colors = colors[: len(labels)]
            else:
                # Extend colors if needed
                while len(colors) < len(labels):
                    colors.extend(self.DEFAULT_BAR_COLORS)
                colors = colors[: len(labels)]

            datasets = [
                {
                    "label": y_axis_label,
                    "data": values,
                    "backgroundColor": colors,
                    "borderColor": colors,
                    "borderWidth": 1,
                }
            ]

        return BarChartData(
            labels=labels,
            datasets=datasets,
            title=title,
            x_axis_label=x_axis_label,
            y_axis_label=y_axis_label,
        )

    def get_line_chart_data(
        self,
        data: Dict[str, List[Dict[str, Any]]],
        title: str = "Динамика",
        x_axis_label: str = "Время",
        y_axis_label: str = "Значения",
        colors: Optional[List[str]] = None,
    ) -> LineChartData:
        """
        Format data for line chart visualization.

        Args:
            data: Dictionary with series names as keys and time series data as values
                  Each time series should be a list of dicts with 'label' and 'value' keys
            title: Chart title
            x_axis_label: X-axis label
            y_axis_label: Y-axis label
            colors: Optional custom colors list

        Returns:
            LineChartData object formatted for Chart.js
        """
        if not data:
            return LineChartData(
                labels=[],
                datasets=[],
                title=title,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
            )

        # Extract all unique labels (time points) and sort them
        all_labels = set()
        for series_data in data.values():
            for point in series_data:
                all_labels.add(point["label"])

        labels = sorted(list(all_labels))

        # Use provided colors or default palette
        series_names = list(data.keys())
        if colors is None:
            colors = self.DEFAULT_LINE_COLORS[: len(series_names)]
        else:
            while len(colors) < len(series_names):
                colors.extend(self.DEFAULT_LINE_COLORS)
            colors = colors[: len(series_names)]

        datasets = []
        for i, (series_name, series_data) in enumerate(data.items()):
            # Create a mapping of label to value for this series
            value_map = {point["label"]: float(point["value"]) for point in series_data}

            # Create data array aligned with labels
            series_values = [value_map.get(label, 0) for label in labels]

            datasets.append(
                {
                    "label": series_name,
                    "data": series_values,
                    "borderColor": colors[i],
                    "backgroundColor": colors[i] + "20",  # Add transparency
                    "fill": False,
                    "tension": 0.1,
                }
            )

        return LineChartData(
            labels=labels,
            datasets=datasets,
            title=title,
            x_axis_label=x_axis_label,
            y_axis_label=y_axis_label,
        )

    def get_time_series_data(
        self,
        data: List[Dict[str, Any]],
        title: str = "Временной ряд",
        x_axis_label: str = "Время",
        y_axis_label: str = "Значения",
        time_unit: str = "month",
        colors: Optional[List[str]] = None,
    ) -> TimeSeriesData:
        """
        Format data for time series chart visualization.

        Args:
            data: List of time series data points with 'date', 'value', and optional 'label' keys
            title: Chart title
            x_axis_label: X-axis label
            y_axis_label: Y-axis label
            time_unit: Time unit for x-axis ('month', 'quarter', 'year')
            colors: Optional custom colors list

        Returns:
            TimeSeriesData object formatted for Chart.js
        """
        if not data:
            return TimeSeriesData(
                datasets=[],
                title=title,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
                time_unit=time_unit,
            )

        # Sort data by date
        sorted_data = sorted(
            data,
            key=lambda x: x["date"]
            if isinstance(x["date"], (date, datetime))
            else datetime.strptime(x["date"], "%Y-%m-%d"),
        )

        # Prepare data for Chart.js time series
        chart_data = []
        for point in sorted_data:
            date_value = point["date"]
            if isinstance(date_value, str):
                date_value = datetime.strptime(date_value, "%Y-%m-%d").date()
            elif isinstance(date_value, datetime):
                date_value = date_value.date()

            chart_data.append({"x": date_value.isoformat(), "y": float(point["value"])})

        # Use provided colors or default
        if colors is None:
            colors = self.DEFAULT_LINE_COLORS

        datasets = [
            {
                "label": y_axis_label,
                "data": chart_data,
                "borderColor": colors[0],
                "backgroundColor": colors[0] + "20",  # Add transparency
                "fill": False,
                "tension": 0.1,
            }
        ]

        return TimeSeriesData(
            datasets=datasets,
            title=title,
            x_axis_label=x_axis_label,
            y_axis_label=y_axis_label,
            time_unit=time_unit,
        )

    def format_branch_analytics_charts(
        self, branch_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format branch analytics data for multiple chart types.

        Args:
            branch_data: Branch analytics data from AnalyticsService

        Returns:
            Dictionary containing formatted chart data for different visualizations
        """
        charts = {}

        if not branch_data.get("branch_metrics"):
            return charts

        branch_metrics = branch_data["branch_metrics"]

        # Premium volume by branch (bar chart)
        premium_data = {
            metric["branch"]["name"]: metric["premium_volume"]
            for metric in branch_metrics
        }
        charts["premium_by_branch"] = self.get_bar_chart_data(
            premium_data,
            title="Объем премий по филиалам",
            x_axis_label="Филиалы",
            y_axis_label="Объем премий (руб.)",
        )

        # Market share pie chart
        market_share_data = {
            metric["branch"]["name"]: metric.get("market_share", 0)
            for metric in branch_metrics
        }
        charts["branch_market_share"] = self.get_pie_chart_data(
            market_share_data, title="Доля рынка по филиалам (%)"
        )

        # Policy count by branch (bar chart)
        policy_count_data = {
            metric["branch"]["name"]: metric["policy_count"]
            for metric in branch_metrics
        }
        charts["policy_count_by_branch"] = self.get_bar_chart_data(
            policy_count_data,
            title="Количество полисов по филиалам",
            x_axis_label="Филиалы",
            y_axis_label="Количество полисов",
        )

        return charts

    def format_insurer_analytics_charts(
        self, insurer_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format insurer analytics data for multiple chart types.

        Args:
            insurer_data: Insurer analytics data from AnalyticsService

        Returns:
            Dictionary containing formatted chart data for different visualizations
        """
        charts = {}

        if not insurer_data.get("insurer_metrics"):
            return charts

        insurer_metrics = insurer_data["insurer_metrics"]

        # Premium volume by insurer (bar chart)
        premium_data = {
            metric["insurer"]["name"]: metric["premium_volume"]
            for metric in insurer_metrics
        }
        charts["premium_by_insurer"] = self.get_bar_chart_data(
            premium_data,
            title="Объем премий по страховщикам",
            x_axis_label="Страховщики",
            y_axis_label="Объем премий (руб.)",
        )

        # Market share pie chart
        market_share_data = {
            metric["insurer"]["name"]: metric.get("market_share", 0)
            for metric in insurer_metrics
        }
        charts["insurer_market_share"] = self.get_pie_chart_data(
            market_share_data, title="Доля рынка по страховщикам (%)"
        )

        # Commission revenue by insurer (bar chart)
        commission_data = {
            metric["insurer"]["name"]: metric["commission_revenue"]
            for metric in insurer_metrics
        }
        charts["commission_by_insurer"] = self.get_bar_chart_data(
            commission_data,
            title="Комиссионный доход по страховщикам",
            x_axis_label="Страховщики",
            y_axis_label="Комиссионный доход (руб.)",
        )

        return charts

    def format_time_series_charts(
        self, time_series_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format time series analytics data for chart visualization.

        Args:
            time_series_data: Time series analytics data from AnalyticsService

        Returns:
            Dictionary containing formatted chart data for time series visualizations
        """
        charts = {}

        # Policy count dynamics
        if time_series_data.get("policy_count_dynamics"):
            charts["policy_count_dynamics"] = self.get_time_series_data(
                time_series_data["policy_count_dynamics"],
                title="Динамика количества полисов",
                x_axis_label="Месяц",
                y_axis_label="Количество полисов",
                time_unit="month",
            )

        # Premium volume dynamics
        if time_series_data.get("premium_volume_dynamics"):
            charts["premium_volume_dynamics"] = self.get_time_series_data(
                time_series_data["premium_volume_dynamics"],
                title="Динамика объема премий",
                x_axis_label="Месяц",
                y_axis_label="Объем премий (руб.)",
                time_unit="month",
            )

        # Commission revenue dynamics
        if time_series_data.get("commission_revenue_dynamics"):
            charts["commission_revenue_dynamics"] = self.get_time_series_data(
                time_series_data["commission_revenue_dynamics"],
                title="Динамика комиссионного дохода",
                x_axis_label="Месяц",
                y_axis_label="Комиссионный доход (руб.)",
                time_unit="month",
            )

        # Seasonal patterns (monthly averages bar chart)
        if time_series_data.get("seasonal_patterns", {}).get("monthly_averages"):
            monthly_averages = time_series_data["seasonal_patterns"]["monthly_averages"]
            # Convert month numbers to month names
            import calendar

            monthly_data = {
                calendar.month_name[month_num]: avg_value
                for month_num, avg_value in monthly_averages.items()
            }
            charts["seasonal_patterns"] = self.get_bar_chart_data(
                monthly_data,
                title="Сезонные паттерны (средние значения по месяцам)",
                x_axis_label="Месяц",
                y_axis_label="Среднее количество полисов",
            )

        # Branch growth trends (multi-line chart)
        if time_series_data.get("branch_growth_trends"):
            branch_trends = time_series_data["branch_growth_trends"]
            charts["branch_growth_trends"] = self.get_line_chart_data(
                branch_trends,
                title="Тренды роста по филиалам",
                x_axis_label="Месяц",
                y_axis_label="Количество полисов",
            )

        return charts

    def format_financial_analytics_charts(
        self, financial_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format financial analytics data for chart visualization.

        Args:
            financial_data: Financial analytics data from AnalyticsService

        Returns:
            Dictionary containing formatted chart data for financial visualizations
        """
        charts = {}

        # Monthly premium forecast (line chart)
        if financial_data.get("monthly_premium_forecast"):
            forecast_data = []
            for forecast in financial_data["monthly_premium_forecast"]:
                forecast_data.append(
                    {
                        "date": forecast["month"],
                        "value": forecast["forecasted_premium"],
                        "label": forecast["month"].strftime("%Y-%m"),
                    }
                )

            charts["premium_forecast"] = self.get_time_series_data(
                forecast_data,
                title="Прогноз поступления премий",
                x_axis_label="Месяц",
                y_axis_label="Прогнозируемые премии (руб.)",
                time_unit="month",
            )

        # Payment status analysis (pie chart)
        if financial_data.get("payment_status_analysis"):
            status_analysis = financial_data["payment_status_analysis"]
            status_data = {
                "Оплачено": status_analysis.get("paid_amount", 0),
                "Ожидает оплаты": status_analysis.get("pending_amount", 0),
                "Просрочено": status_analysis.get("overdue_amount", 0),
            }
            charts["payment_status"] = self.get_pie_chart_data(
                status_data, title="Статус платежей (руб.)"
            )

        # Overdue payments by days (bar chart)
        if financial_data.get("overdue_payments_analysis", {}).get("overdue_by_days"):
            overdue_by_days = financial_data["overdue_payments_analysis"][
                "overdue_by_days"
            ]
            charts["overdue_by_days"] = self.get_bar_chart_data(
                overdue_by_days,
                title="Просроченные платежи по дням",
                x_axis_label="Период просрочки",
                y_axis_label="Сумма просрочки (руб.)",
            )

        return charts

    def to_json(
        self,
        chart_data: Union[PieChartData, BarChartData, LineChartData, TimeSeriesData],
    ) -> str:
        """
        Convert chart data to JSON string for JavaScript consumption.

        Args:
            chart_data: Chart data object

        Returns:
            JSON string representation of the chart data
        """

        def decimal_serializer(obj):
            """Custom serializer for Decimal objects."""
            if isinstance(obj, Decimal):
                return float(obj)
            elif isinstance(obj, (date, datetime)):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        return json.dumps(
            chart_data.__dict__, default=decimal_serializer, ensure_ascii=False
        )
