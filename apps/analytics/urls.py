from django.urls import path
from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("branches/", views.BranchAnalyticsView.as_view(), name="branch_analytics"),
    path(
        "branches-v2/",
        views.BranchPortfolioAnalyticsV2View.as_view(),
        name="branch_portfolio_analytics_v2",
    ),
    path("insurers/", views.InsurerAnalyticsView.as_view(), name="insurer_analytics"),
    path("clients/", views.ClientAnalyticsView.as_view(), name="client_analytics"),
    path(
        "financial/", views.FinancialAnalyticsView.as_view(), name="financial_analytics"
    ),
    path(
        "financial-history/",
        views.FinancialHistoryView.as_view(),
        name="financial_history",
    ),
    path(
        "time-series/",
        views.TimeSeriesAnalyticsView.as_view(),
        name="time_series_analytics",
    ),
]
