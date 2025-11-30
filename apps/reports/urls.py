from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    # Главная страница экспорта
    path("", views.ExportsIndexView.as_view(), name="index"),
    # Кастомный экспорт
    path("custom/", views.CustomExportView.as_view(), name="custom_export"),
    path(
        "custom/template/<int:pk>/delete/",
        views.DeleteTemplateView.as_view(),
        name="delete_template",
    ),
    # Готовые экспорты (старые функции для обратной совместимости)
    path("export/policies/", views.export_policies_excel, name="export_policies"),
    path("export/payments/", views.export_payments_excel, name="export_payments"),
    path(
        "export/thursday/", views.export_thursday_report, name="export_thursday_report"
    ),
    path(
        "export/policy-expiration/",
        views.export_policy_expiration,
        name="export_policy_expiration",
    ),
    path(
        "export/commission-report/",
        views.export_commission_report,
        name="export_commission_report",
    ),
]
