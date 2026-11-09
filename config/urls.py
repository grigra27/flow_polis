"""
URL configuration for insurance_broker project.
"""
from apps.policies.flow_api import link_status
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.policies import flow_views

urlpatterns = [
    path(
        "internal/flow/v1/summaries/<int:summary_id>/links/",
        link_status,
        name="flow-link-status",
    ),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
    path("clients/", include("apps.clients.urls")),
    path("insurers/", include("apps.insurers.urls")),
    path("policies/", include("apps.policies.urls")),
    path("flow/from-zs/", flow_views.landing, name="flow_policy_landing"),
    path(
        "flow/from-zs/review/<slug:key>/", flow_views.review, name="flow_policy_review"
    ),
    path("reports/", include("apps.reports.urls")),
    path("analytics/", include("apps.analytics.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    try:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

# Customize admin
admin.site.site_header = "Система управления полисами"
admin.site.site_title = "Страховой брокер"
admin.site.index_title = "Администрирование"
