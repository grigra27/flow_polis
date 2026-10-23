from django.urls import path, re_path
from django.views.generic import RedirectView

from . import views

app_name = "analytics"

# Адреса старых страниц аналитики (удалены на этапе 5 плана
# docs/analytics-2.0-plan.md) ведут на сводку. Старые insurers/, clients/
# и osago/ совпадают с вкладками и открывают их.
OLD_PAGES = [
    "branches/",
    "branches-v2/",
    "financial/",
    "financial-history/",
    "time-series/",
]

urlpatterns = [
    path("list/<slug:key>/", views.DrilldownView.as_view(), name="list"),
    *[
        path(
            "" if key == "summary" else f"{key.replace('_', '-')}/",
            views.AnalyticsTabView.as_view(tab=key),
            name=key,
        )
        for key in views.TAB_KEYS
    ],
    *[
        path(old, RedirectView.as_view(pattern_name="analytics:summary"))
        for old in OLD_PAGES
    ],
    # До этапа 5 аналитика жила по адресу v2/ — сохраняем закладки.
    re_path(
        r"^v2/(?P<rest>.*)$",
        RedirectView.as_view(url="/analytics/%(rest)s", query_string=True),
    ),
]
