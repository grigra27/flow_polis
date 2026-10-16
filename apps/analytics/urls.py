from django.urls import path
from . import views, views_v2

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
    path("osago/", views.OsagoAnalyticsView.as_view(), name="osago_analytics"),
    # Аналитика 2.0 (docs/analytics-2.0-plan.md); до этапа 5 — по адресу v2/.
    path("v2/list/<slug:key>/", views_v2.DrilldownView.as_view(), name="v2_list"),
    *[
        path(
            "v2/" if key == "summary" else f"v2/{key.replace('_', '-')}/",
            views_v2.AnalyticsTabView.as_view(tab=key),
            name=f"v2_{key}",
        )
        for key in views_v2.TAB_KEYS
    ],
]
