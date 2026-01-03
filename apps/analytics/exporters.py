"""
Analytics exporters for exporting analytical data to various formats.
This module provides functionality to export analytics data to Excel format.
"""

from decimal import Decimal
from datetime import date, datetime
from typing import Dict, Any, List, Optional
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


class AnalyticsExporter:
    """
    Exporter for analytics data to Excel format.
    Handles export of all types of analytics with proper formatting and headers.
    """

    def __init__(self):
        self.header_font = Font(bold=True, color="FFFFFF")
        self.header_fill = PatternFill(
            start_color="366092", end_color="366092", fill_type="solid"
        )
        self.border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        self.center_alignment = Alignment(horizontal="center", vertical="center")
        self.right_alignment = Alignment(horizontal="right", vertical="center")

    def _format_value(self, value: Any) -> str:
        """
        Format a value for display in Excel.

        Args:
            value: Value to format

        Returns:
            Formatted string representation
        """
        if value is None:
            return ""
        elif isinstance(value, Decimal):
            return f"{value:,.2f}"
        elif isinstance(value, (int, float)):
            return f"{value:,}"
        elif isinstance(value, (date, datetime)):
            return value.strftime("%Y-%m-%d")
        elif isinstance(value, dict):
            return str(value)
        else:
            return str(value)

    def _apply_header_style(self, worksheet, row_num: int, num_columns: int):
        """
        Apply header styling to a row.

        Args:
            worksheet: Excel worksheet
            row_num: Row number to style
            num_columns: Number of columns to style
        """
        for col in range(1, num_columns + 1):
            cell = worksheet.cell(row=row_num, column=col)
            cell.font = self.header_font
            cell.fill = self.header_fill
            cell.alignment = self.center_alignment
            cell.border = self.border

    def _apply_data_style(
        self, worksheet, start_row: int, end_row: int, num_columns: int
    ):
        """
        Apply data styling to rows.

        Args:
            worksheet: Excel worksheet
            start_row: Starting row number
            end_row: Ending row number
            num_columns: Number of columns to style
        """
        for row in range(start_row, end_row + 1):
            for col in range(1, num_columns + 1):
                cell = worksheet.cell(row=row, column=col)
                cell.border = self.border
                # Right-align numeric columns
                if col > 1:  # Assuming first column is text
                    cell.alignment = self.right_alignment

    def _auto_adjust_columns(self, worksheet):
        """
        Auto-adjust column widths based on content.

        Args:
            worksheet: Excel worksheet
        """
        for column in worksheet.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)

            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass

            adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
            worksheet.column_dimensions[column_letter].width = adjusted_width

    def export_dashboard_metrics(
        self, metrics: Dict[str, Any], applied_filters: Optional[Dict[str, Any]] = None
    ) -> HttpResponse:
        """
        Export dashboard metrics to Excel.

        Args:
            metrics: Dashboard metrics data
            applied_filters: Applied filters information

        Returns:
            HttpResponse with Excel file
        """
        try:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Dashboard Metrics"

            # Add title
            worksheet.cell(row=1, column=1, value="Dashboard Metrics Report")
            worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
            worksheet.merge_cells("A1:B1")

            # Add export date
            worksheet.cell(
                row=2,
                column=1,
                value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )

            # Add filter information if provided
            current_row = 3
            if applied_filters:
                worksheet.cell(row=current_row, column=1, value="Applied Filters:")
                worksheet.cell(row=current_row, column=1).font = Font(bold=True)
                current_row += 1

                for filter_name, filter_value in applied_filters.items():
                    if filter_value:
                        worksheet.cell(
                            row=current_row,
                            column=1,
                            value=f"  {filter_name}: {filter_value}",
                        )
                        current_row += 1
                current_row += 1

            # Add metrics data
            worksheet.cell(row=current_row, column=1, value="Metric")
            worksheet.cell(row=current_row, column=2, value="Value")
            self._apply_header_style(worksheet, current_row, 2)
            current_row += 1

            # Key metrics
            metrics_to_export = [
                ("Total Premium Volume", metrics.get("total_premium_volume", 0)),
                (
                    "Total Commission Revenue",
                    metrics.get("total_commission_revenue", 0),
                ),
                ("Total Policy Count", metrics.get("total_policy_count", 0)),
                ("Total Insurance Sum", metrics.get("total_insurance_sum", 0)),
                ("Active Policies Count", metrics.get("active_policies_count", 0)),
                (
                    "Average Commission Rate (%)",
                    metrics.get("average_commission_rate", 0),
                ),
                ("Current Year Growth (%)", metrics.get("current_year_growth", 0)),
            ]

            for metric_name, metric_value in metrics_to_export:
                worksheet.cell(row=current_row, column=1, value=metric_name)
                worksheet.cell(
                    row=current_row, column=2, value=self._format_value(metric_value)
                )
                current_row += 1

            # Apply styling
            self._apply_data_style(
                worksheet, current_row - len(metrics_to_export), current_row - 1, 2
            )
            self._auto_adjust_columns(worksheet)

            # Save to BytesIO
            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Create response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response[
                "Content-Disposition"
            ] = f'attachment; filename="dashboard_metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

        except Exception as e:
            logger.error(f"Error exporting dashboard metrics: {e}")
            raise

    def export_branch_analytics(
        self,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> HttpResponse:
        """
        Export branch analytics to Excel.

        Args:
            analytics: Branch analytics data
            applied_filters: Applied filters information

        Returns:
            HttpResponse with Excel file
        """
        try:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Branch Analytics"

            # Add title and metadata
            worksheet.cell(row=1, column=1, value="Branch Analytics Report")
            worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
            worksheet.merge_cells("A1:F1")

            worksheet.cell(
                row=2,
                column=1,
                value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )

            current_row = 3
            if applied_filters:
                worksheet.cell(row=current_row, column=1, value="Applied Filters:")
                worksheet.cell(row=current_row, column=1).font = Font(bold=True)
                current_row += 1

                for filter_name, filter_value in applied_filters.items():
                    if filter_value:
                        worksheet.cell(
                            row=current_row,
                            column=1,
                            value=f"  {filter_name}: {filter_value}",
                        )
                        current_row += 1
                current_row += 1

            # Headers
            headers = [
                "Branch Name",
                "Premium Volume",
                "Commission Revenue",
                "Policy Count",
                "Insurance Sum",
                "Market Share (%)",
            ]
            for col, header in enumerate(headers, 1):
                worksheet.cell(row=current_row, column=col, value=header)

            self._apply_header_style(worksheet, current_row, len(headers))
            current_row += 1

            # Data rows
            branch_metrics = analytics.get("branch_metrics", [])
            start_data_row = current_row

            for branch_metric in branch_metrics:
                branch_info = branch_metric.get("branch", {})
                worksheet.cell(
                    row=current_row, column=1, value=branch_info.get("name", "")
                )
                worksheet.cell(
                    row=current_row,
                    column=2,
                    value=self._format_value(branch_metric.get("premium_volume", 0)),
                )
                worksheet.cell(
                    row=current_row,
                    column=3,
                    value=self._format_value(
                        branch_metric.get("commission_revenue", 0)
                    ),
                )
                worksheet.cell(
                    row=current_row,
                    column=4,
                    value=self._format_value(branch_metric.get("policy_count", 0)),
                )
                worksheet.cell(
                    row=current_row,
                    column=5,
                    value=self._format_value(branch_metric.get("insurance_sum", 0)),
                )
                worksheet.cell(
                    row=current_row,
                    column=6,
                    value=self._format_value(branch_metric.get("market_share", 0)),
                )
                current_row += 1

            # Apply styling
            if current_row > start_data_row:
                self._apply_data_style(
                    worksheet, start_data_row, current_row - 1, len(headers)
                )

            self._auto_adjust_columns(worksheet)

            # Save to BytesIO
            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Create response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response[
                "Content-Disposition"
            ] = f'attachment; filename="branch_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

        except Exception as e:
            logger.error(f"Error exporting branch analytics: {e}")
            raise

    def export_insurer_analytics(
        self,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> HttpResponse:
        """
        Export insurer analytics to Excel.

        Args:
            analytics: Insurer analytics data
            applied_filters: Applied filters information

        Returns:
            HttpResponse with Excel file
        """
        try:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Insurer Analytics"

            # Add title and metadata
            worksheet.cell(row=1, column=1, value="Insurer Analytics Report")
            worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
            worksheet.merge_cells("A1:F1")

            worksheet.cell(
                row=2,
                column=1,
                value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )

            current_row = 3
            if applied_filters:
                worksheet.cell(row=current_row, column=1, value="Applied Filters:")
                worksheet.cell(row=current_row, column=1).font = Font(bold=True)
                current_row += 1

                for filter_name, filter_value in applied_filters.items():
                    if filter_value:
                        worksheet.cell(
                            row=current_row,
                            column=1,
                            value=f"  {filter_name}: {filter_value}",
                        )
                        current_row += 1
                current_row += 1

            # Headers
            headers = [
                "Insurer Name",
                "Premium Volume",
                "Commission Revenue",
                "Policy Count",
                "Insurance Sum",
                "Market Share (%)",
            ]
            for col, header in enumerate(headers, 1):
                worksheet.cell(row=current_row, column=col, value=header)

            self._apply_header_style(worksheet, current_row, len(headers))
            current_row += 1

            # Data rows
            insurer_metrics = analytics.get("insurer_metrics", [])
            start_data_row = current_row

            for insurer_metric in insurer_metrics:
                insurer_info = insurer_metric.get("insurer", {})
                worksheet.cell(
                    row=current_row, column=1, value=insurer_info.get("name", "")
                )
                worksheet.cell(
                    row=current_row,
                    column=2,
                    value=self._format_value(insurer_metric.get("premium_volume", 0)),
                )
                worksheet.cell(
                    row=current_row,
                    column=3,
                    value=self._format_value(
                        insurer_metric.get("commission_revenue", 0)
                    ),
                )
                worksheet.cell(
                    row=current_row,
                    column=4,
                    value=self._format_value(insurer_metric.get("policy_count", 0)),
                )
                worksheet.cell(
                    row=current_row,
                    column=5,
                    value=self._format_value(insurer_metric.get("insurance_sum", 0)),
                )
                worksheet.cell(
                    row=current_row,
                    column=6,
                    value=self._format_value(insurer_metric.get("market_share", 0)),
                )
                current_row += 1

            # Apply styling
            if current_row > start_data_row:
                self._apply_data_style(
                    worksheet, start_data_row, current_row - 1, len(headers)
                )

            self._auto_adjust_columns(worksheet)

            # Save to BytesIO
            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Create response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response[
                "Content-Disposition"
            ] = f'attachment; filename="insurer_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

        except Exception as e:
            logger.error(f"Error exporting insurer analytics: {e}")
            raise

    def export_client_analytics(
        self,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> HttpResponse:
        """
        Export client analytics to Excel.

        Args:
            analytics: Client analytics data
            applied_filters: Applied filters information

        Returns:
            HttpResponse with Excel file
        """
        try:
            workbook = Workbook()

            # Create multiple sheets for different client rankings

            # Sheet 1: Top Clients by Insurance Sum
            ws1 = workbook.active
            ws1.title = "Top by Insurance Sum"
            self._create_client_sheet(
                ws1,
                "Top Clients by Insurance Sum",
                analytics.get("top_clients_by_insurance_sum", []),
                applied_filters,
            )

            # Sheet 2: Top Clients by Commission
            ws2 = workbook.create_sheet(title="Top by Commission")
            self._create_client_sheet(
                ws2,
                "Top Clients by Commission Revenue",
                analytics.get("top_clients_by_commission", []),
                applied_filters,
            )

            # Sheet 3: Top Clients by Policy Count
            ws3 = workbook.create_sheet(title="Top by Policy Count")
            self._create_client_sheet(
                ws3,
                "Top Clients by Policy Count",
                analytics.get("top_clients_by_policy_count", []),
                applied_filters,
            )

            # Save to BytesIO
            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Create response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response[
                "Content-Disposition"
            ] = f'attachment; filename="client_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

        except Exception as e:
            logger.error(f"Error exporting client analytics: {e}")
            raise

    def _create_client_sheet(
        self,
        worksheet,
        title: str,
        client_metrics: List[Dict],
        applied_filters: Optional[Dict[str, Any]] = None,
    ):
        """
        Create a client analytics sheet.

        Args:
            worksheet: Excel worksheet
            title: Sheet title
            client_metrics: List of client metrics
            applied_filters: Applied filters information
        """
        # Add title and metadata
        worksheet.cell(row=1, column=1, value=title)
        worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
        worksheet.merge_cells("A1:G1")

        worksheet.cell(
            row=2,
            column=1,
            value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        current_row = 3
        if applied_filters:
            worksheet.cell(row=current_row, column=1, value="Applied Filters:")
            worksheet.cell(row=current_row, column=1).font = Font(bold=True)
            current_row += 1

            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    worksheet.cell(
                        row=current_row,
                        column=1,
                        value=f"  {filter_name}: {filter_value}",
                    )
                    current_row += 1
            current_row += 1

        # Headers
        headers = [
            "Client Name",
            "INN",
            "Premium Volume",
            "Commission Revenue",
            "Policy Count",
            "Insurance Sum",
            "Avg Policy Value",
        ]
        for col, header in enumerate(headers, 1):
            worksheet.cell(row=current_row, column=col, value=header)

        self._apply_header_style(worksheet, current_row, len(headers))
        current_row += 1

        # Data rows
        start_data_row = current_row

        for client_metric in client_metrics:
            client_info = client_metric.get("client", {})
            worksheet.cell(row=current_row, column=1, value=client_info.get("name", ""))
            worksheet.cell(row=current_row, column=2, value=client_info.get("inn", ""))
            worksheet.cell(
                row=current_row,
                column=3,
                value=self._format_value(client_metric.get("premium_volume", 0)),
            )
            worksheet.cell(
                row=current_row,
                column=4,
                value=self._format_value(client_metric.get("commission_revenue", 0)),
            )
            worksheet.cell(
                row=current_row,
                column=5,
                value=self._format_value(client_metric.get("policy_count", 0)),
            )
            worksheet.cell(
                row=current_row,
                column=6,
                value=self._format_value(client_metric.get("insurance_sum", 0)),
            )
            worksheet.cell(
                row=current_row,
                column=7,
                value=self._format_value(client_metric.get("average_policy_value", 0)),
            )
            current_row += 1

        # Apply styling
        if current_row > start_data_row:
            self._apply_data_style(
                worksheet, start_data_row, current_row - 1, len(headers)
            )

        self._auto_adjust_columns(worksheet)

    def export_financial_analytics(
        self,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> HttpResponse:
        """
        Export financial analytics to Excel.

        Args:
            analytics: Financial analytics data
            applied_filters: Applied filters information

        Returns:
            HttpResponse with Excel file
        """
        try:
            workbook = Workbook()

            # Sheet 1: Monthly Forecasts
            ws1 = workbook.active
            ws1.title = "Monthly Forecasts"
            self._create_forecast_sheet(ws1, analytics, applied_filters)

            # Sheet 2: Payment Status Analysis
            ws2 = workbook.create_sheet(title="Payment Analysis")
            self._create_payment_analysis_sheet(ws2, analytics, applied_filters)

            # Sheet 3: Overdue Analysis
            ws3 = workbook.create_sheet(title="Overdue Analysis")
            self._create_overdue_analysis_sheet(ws3, analytics, applied_filters)

            # Save to BytesIO
            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Create response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response[
                "Content-Disposition"
            ] = f'attachment; filename="financial_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

        except Exception as e:
            logger.error(f"Error exporting financial analytics: {e}")
            raise

    def _create_forecast_sheet(
        self,
        worksheet,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ):
        """Create monthly forecast sheet."""
        # Add title and metadata
        worksheet.cell(row=1, column=1, value="Monthly Financial Forecasts")
        worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
        worksheet.merge_cells("A1:F1")

        worksheet.cell(
            row=2,
            column=1,
            value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        current_row = 3
        if applied_filters:
            worksheet.cell(row=current_row, column=1, value="Applied Filters:")
            worksheet.cell(row=current_row, column=1).font = Font(bold=True)
            current_row += 1

            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    worksheet.cell(
                        row=current_row,
                        column=1,
                        value=f"  {filter_name}: {filter_value}",
                    )
                    current_row += 1
            current_row += 1

        # Headers
        headers = [
            "Month",
            "Forecasted Premium",
            "Forecasted Commission",
            "Actual Premium",
            "Actual Commission",
            "Confidence Level (%)",
        ]
        for col, header in enumerate(headers, 1):
            worksheet.cell(row=current_row, column=col, value=header)

        self._apply_header_style(worksheet, current_row, len(headers))
        current_row += 1

        # Data rows
        monthly_forecasts = analytics.get("monthly_premium_forecast", [])
        start_data_row = current_row

        for forecast in monthly_forecasts:
            worksheet.cell(
                row=current_row,
                column=1,
                value=self._format_value(forecast.get("month")),
            )
            worksheet.cell(
                row=current_row,
                column=2,
                value=self._format_value(forecast.get("forecasted_premium", 0)),
            )
            worksheet.cell(
                row=current_row,
                column=3,
                value=self._format_value(forecast.get("forecasted_commission", 0)),
            )
            worksheet.cell(
                row=current_row,
                column=4,
                value=self._format_value(forecast.get("actual_premium", 0))
                if forecast.get("actual_premium")
                else "N/A",
            )
            worksheet.cell(
                row=current_row,
                column=5,
                value=self._format_value(forecast.get("actual_commission", 0))
                if forecast.get("actual_commission")
                else "N/A",
            )
            worksheet.cell(
                row=current_row,
                column=6,
                value=self._format_value(forecast.get("confidence_level", 0)),
            )
            current_row += 1

        # Apply styling
        if current_row > start_data_row:
            self._apply_data_style(
                worksheet, start_data_row, current_row - 1, len(headers)
            )

        self._auto_adjust_columns(worksheet)

    def _create_payment_analysis_sheet(
        self,
        worksheet,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ):
        """Create payment status analysis sheet."""
        # Add title and metadata
        worksheet.cell(row=1, column=1, value="Payment Status Analysis")
        worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
        worksheet.merge_cells("A1:B1")

        worksheet.cell(
            row=2,
            column=1,
            value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        current_row = 3
        if applied_filters:
            worksheet.cell(row=current_row, column=1, value="Applied Filters:")
            worksheet.cell(row=current_row, column=1).font = Font(bold=True)
            current_row += 1

            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    worksheet.cell(
                        row=current_row,
                        column=1,
                        value=f"  {filter_name}: {filter_value}",
                    )
                    current_row += 1
            current_row += 1

        # Payment status summary
        payment_analysis = analytics.get("payment_status_analysis", {})

        worksheet.cell(row=current_row, column=1, value="Payment Status")
        worksheet.cell(row=current_row, column=2, value="Count")
        worksheet.cell(row=current_row, column=3, value="Amount")
        self._apply_header_style(worksheet, current_row, 3)
        current_row += 1

        status_data = [
            (
                "Total Payments",
                payment_analysis.get("total_payments", 0),
                payment_analysis.get("paid_amount", 0)
                + payment_analysis.get("pending_amount", 0)
                + payment_analysis.get("overdue_amount", 0),
            ),
            (
                "Paid Payments",
                payment_analysis.get("paid_payments", 0),
                payment_analysis.get("paid_amount", 0),
            ),
            (
                "Pending Payments",
                payment_analysis.get("pending_payments", 0),
                payment_analysis.get("pending_amount", 0),
            ),
            (
                "Overdue Payments",
                payment_analysis.get("overdue_payments", 0),
                payment_analysis.get("overdue_amount", 0),
            ),
        ]

        start_data_row = current_row
        for status, count, amount in status_data:
            worksheet.cell(row=current_row, column=1, value=status)
            worksheet.cell(row=current_row, column=2, value=self._format_value(count))
            worksheet.cell(row=current_row, column=3, value=self._format_value(amount))
            current_row += 1

        # Apply styling
        self._apply_data_style(worksheet, start_data_row, current_row - 1, 3)

        # Add payment discipline rate
        current_row += 1
        worksheet.cell(row=current_row, column=1, value="Payment Discipline Rate (%)")
        worksheet.cell(
            row=current_row,
            column=2,
            value=self._format_value(
                payment_analysis.get("payment_discipline_rate", 0)
            ),
        )
        worksheet.cell(row=current_row, column=1).font = Font(bold=True)

        self._auto_adjust_columns(worksheet)

    def _create_overdue_analysis_sheet(
        self,
        worksheet,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ):
        """Create overdue analysis sheet."""
        # Add title and metadata
        worksheet.cell(row=1, column=1, value="Overdue Payments Analysis")
        worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
        worksheet.merge_cells("A1:B1")

        worksheet.cell(
            row=2,
            column=1,
            value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        current_row = 3
        if applied_filters:
            worksheet.cell(row=current_row, column=1, value="Applied Filters:")
            worksheet.cell(row=current_row, column=1).font = Font(bold=True)
            current_row += 1

            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    worksheet.cell(
                        row=current_row,
                        column=1,
                        value=f"  {filter_name}: {filter_value}",
                    )
                    current_row += 1
            current_row += 1

        overdue_analysis = analytics.get("overdue_payments_analysis", {})

        # Overdue by days
        worksheet.cell(row=current_row, column=1, value="Overdue by Days")
        worksheet.cell(row=current_row, column=2, value="Amount")
        self._apply_header_style(worksheet, current_row, 2)
        current_row += 1

        overdue_by_days = overdue_analysis.get("overdue_by_days", {})
        start_data_row = current_row
        for days_range, amount in overdue_by_days.items():
            worksheet.cell(row=current_row, column=1, value=days_range)
            worksheet.cell(row=current_row, column=2, value=self._format_value(amount))
            current_row += 1

        if current_row > start_data_row:
            self._apply_data_style(worksheet, start_data_row, current_row - 1, 2)

        # Add summary statistics
        current_row += 1
        worksheet.cell(row=current_row, column=1, value="Total Overdue Amount")
        worksheet.cell(
            row=current_row,
            column=2,
            value=self._format_value(overdue_analysis.get("total_overdue_amount", 0)),
        )
        worksheet.cell(row=current_row, column=1).font = Font(bold=True)
        current_row += 1

        worksheet.cell(row=current_row, column=1, value="Average Overdue Days")
        worksheet.cell(
            row=current_row,
            column=2,
            value=self._format_value(overdue_analysis.get("average_overdue_days", 0)),
        )
        worksheet.cell(row=current_row, column=1).font = Font(bold=True)

        self._auto_adjust_columns(worksheet)

    def export_time_series_analytics(
        self,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> HttpResponse:
        """
        Export time series analytics to Excel.

        Args:
            analytics: Time series analytics data
            applied_filters: Applied filters information

        Returns:
            HttpResponse with Excel file
        """
        try:
            workbook = Workbook()

            # Sheet 1: Time Series Data
            ws1 = workbook.active
            ws1.title = "Time Series Data"
            self._create_time_series_sheet(ws1, analytics, applied_filters)

            # Sheet 2: Seasonal Patterns
            ws2 = workbook.create_sheet(title="Seasonal Patterns")
            self._create_seasonal_patterns_sheet(ws2, analytics, applied_filters)

            # Save to BytesIO
            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Create response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response[
                "Content-Disposition"
            ] = f'attachment; filename="time_series_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

        except Exception as e:
            logger.error(f"Error exporting time series analytics: {e}")
            raise

    def _create_time_series_sheet(
        self,
        worksheet,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ):
        """Create time series data sheet."""
        # Add title and metadata
        worksheet.cell(row=1, column=1, value="Time Series Analytics")
        worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
        worksheet.merge_cells("A1:D1")

        worksheet.cell(
            row=2,
            column=1,
            value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        current_row = 3
        if applied_filters:
            worksheet.cell(row=current_row, column=1, value="Applied Filters:")
            worksheet.cell(row=current_row, column=1).font = Font(bold=True)
            current_row += 1

            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    worksheet.cell(
                        row=current_row,
                        column=1,
                        value=f"  {filter_name}: {filter_value}",
                    )
                    current_row += 1
            current_row += 1

        # Headers
        headers = ["Date", "Policy Count", "Premium Volume", "Commission Revenue"]
        for col, header in enumerate(headers, 1):
            worksheet.cell(row=current_row, column=col, value=header)

        self._apply_header_style(worksheet, current_row, len(headers))
        current_row += 1

        # Combine all time series data by date
        policy_dynamics = {
            item["date"]: item["value"]
            for item in analytics.get("policy_count_dynamics", [])
        }
        premium_dynamics = {
            item["date"]: item["value"]
            for item in analytics.get("premium_volume_dynamics", [])
        }
        commission_dynamics = {
            item["date"]: item["value"]
            for item in analytics.get("commission_revenue_dynamics", [])
        }

        # Get all unique dates and sort them
        all_dates = sorted(
            set(
                list(policy_dynamics.keys())
                + list(premium_dynamics.keys())
                + list(commission_dynamics.keys())
            )
        )

        start_data_row = current_row
        for date_val in all_dates:
            worksheet.cell(
                row=current_row, column=1, value=self._format_value(date_val)
            )
            worksheet.cell(
                row=current_row,
                column=2,
                value=self._format_value(policy_dynamics.get(date_val, 0)),
            )
            worksheet.cell(
                row=current_row,
                column=3,
                value=self._format_value(premium_dynamics.get(date_val, 0)),
            )
            worksheet.cell(
                row=current_row,
                column=4,
                value=self._format_value(commission_dynamics.get(date_val, 0)),
            )
            current_row += 1

        # Apply styling
        if current_row > start_data_row:
            self._apply_data_style(
                worksheet, start_data_row, current_row - 1, len(headers)
            )

        self._auto_adjust_columns(worksheet)

    def _create_seasonal_patterns_sheet(
        self,
        worksheet,
        analytics: Dict[str, Any],
        applied_filters: Optional[Dict[str, Any]] = None,
    ):
        """Create seasonal patterns sheet."""
        # Add title and metadata
        worksheet.cell(row=1, column=1, value="Seasonal Patterns Analysis")
        worksheet.cell(row=1, column=1).font = Font(size=16, bold=True)
        worksheet.merge_cells("A1:C1")

        worksheet.cell(
            row=2,
            column=1,
            value=f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )

        current_row = 3
        if applied_filters:
            worksheet.cell(row=current_row, column=1, value="Applied Filters:")
            worksheet.cell(row=current_row, column=1).font = Font(bold=True)
            current_row += 1

            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    worksheet.cell(
                        row=current_row,
                        column=1,
                        value=f"  {filter_name}: {filter_value}",
                    )
                    current_row += 1
            current_row += 1

        seasonal_patterns = analytics.get("seasonal_patterns", {})

        # Monthly averages
        worksheet.cell(row=current_row, column=1, value="Month")
        worksheet.cell(row=current_row, column=2, value="Average Value")
        worksheet.cell(row=current_row, column=3, value="Seasonal Index")
        self._apply_header_style(worksheet, current_row, 3)
        current_row += 1

        monthly_averages = seasonal_patterns.get("monthly_averages", {})
        seasonal_indices = seasonal_patterns.get("seasonal_indices", {})

        start_data_row = current_row
        for month_num in range(1, 13):
            month_name = datetime(2023, month_num, 1).strftime("%B")
            worksheet.cell(row=current_row, column=1, value=month_name)
            worksheet.cell(
                row=current_row,
                column=2,
                value=self._format_value(monthly_averages.get(month_num, 0)),
            )
            worksheet.cell(
                row=current_row,
                column=3,
                value=self._format_value(seasonal_indices.get(month_num, 0)),
            )
            current_row += 1

        # Apply styling
        self._apply_data_style(worksheet, start_data_row, current_row - 1, 3)

        # Add summary statistics
        current_row += 1
        worksheet.cell(row=current_row, column=1, value="Seasonality Strength")
        worksheet.cell(
            row=current_row,
            column=2,
            value=self._format_value(seasonal_patterns.get("seasonality_strength", 0)),
        )
        worksheet.cell(row=current_row, column=1).font = Font(bold=True)

        self._auto_adjust_columns(worksheet)
