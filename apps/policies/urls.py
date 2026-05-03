from django.urls import path
from . import views
from apps.billing import views as billing_views

app_name = "policies"

urlpatterns = [
    path("", views.PolicyListView.as_view(), name="list"),
    path("<int:pk>/", views.PolicyDetailView.as_view(), name="detail"),
    path("payments/", views.PaymentScheduleListView.as_view(), name="payments"),
    path(
        "payments/scheduled/",
        billing_views.BillingPeriodListView.as_view(),
        name="scheduled_payments",
    ),
    path(
        "payments/scheduled/tasks/<int:pk>/",
        billing_views.BillingTaskDetailView.as_view(),
        name="scheduled_payment_task",
    ),
    path(
        "payments/scheduled/tasks/<int:pk>/update/",
        billing_views.BillingTaskUpdateView.as_view(),
        name="scheduled_payment_task_update",
    ),
    path(
        "payments/scheduled/bulk-update/",
        billing_views.BillingTaskBulkUpdateView.as_view(),
        name="scheduled_payment_bulk_update",
    ),
]
