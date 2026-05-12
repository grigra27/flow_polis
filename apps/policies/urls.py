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
        "payments/prolongation/",
        billing_views.BillingProlongationPlaceholderView.as_view(),
        name="prolongation",
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
        "payments/scheduled/tasks/<int:pk>/send-insurer-email/",
        billing_views.BillingTaskSendInsurerEmailView.as_view(),
        name="scheduled_payment_send_insurer_email",
    ),
    path(
        "payments/scheduled/tasks/<int:pk>/send-alliance-email/",
        billing_views.BillingTaskSendAllianceEmailView.as_view(),
        name="scheduled_payment_send_alliance_email",
    ),
    path(
        "payments/scheduled/tasks/<int:pk>/retry-email/<int:email_id>/",
        billing_views.BillingTaskRetryEmailView.as_view(),
        name="scheduled_payment_retry_email",
    ),
    path(
        "payments/scheduled/bulk-update/",
        billing_views.BillingTaskBulkUpdateView.as_view(),
        name="scheduled_payment_bulk_update",
    ),
]
