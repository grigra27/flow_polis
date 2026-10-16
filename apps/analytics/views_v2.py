"""
Аналитика 2.0: одна страница с вкладками, общие фильтры в GET, список
«под цифрой» с выгрузкой. План — docs/analytics-2.0-plan.md.

До этапа 5 плана живёт по адресу /analytics/v2/ рядом со старыми страницами.
"""

from importlib import import_module

from django.http import Http404
from django.views.generic import TemplateView

from apps.accounts.mixins import SuperuserRequiredMixin
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager

from . import drilldown
from .export import table_response
from .filters import AnalyticsParams

# (ключ, название, иконка, модуль sections или None — вкладка ещё не готова)
TABS = [
    ("summary", "Сводка", "bi-speedometer2", "summary"),
    ("money", "Деньги", "bi-cash-stack", "money"),
    ("sales", "Продажи", "bi-graph-up-arrow", "sales"),
    ("portfolio", "Портфель", "bi-briefcase", "portfolio"),
    ("insurers", "Страховщики", "bi-building", "insurers"),
    ("channels", "Каналы", "bi-diagram-3", "channels"),
    ("clients", "Клиенты", "bi-people", "clients"),
    ("osago", "ОСАГО", "bi-car-front", "osago"),
    ("data_quality", "Качество данных", "bi-clipboard-check", "data_quality"),
]
TAB_KEYS = [key for key, *_ in TABS]


def tab_url_name(key: str) -> str:
    return f"analytics:v2_{key}"


class AnalyticsV2Mixin(SuperuserRequiredMixin):
    def get_params(self) -> AnalyticsParams:
        if not hasattr(self, "_params"):
            self._params = AnalyticsParams.from_query(self.request.GET)
        return self._params

    def filter_context(self, params: AnalyticsParams) -> dict:
        def options(queryset, label_field, selected):
            return [
                {"id": pk, "name": name, "selected": pk in selected}
                for pk, name in queryset.values_list("id", label_field)
            ]

        return {
            "params": params,
            "filter_options": [
                {
                    "name": "branch",
                    "label": "Филиал",
                    "options": options(
                        Branch.objects.order_by("branch_name"),
                        "branch_name",
                        params.branch,
                    ),
                },
                {
                    "name": "insurer",
                    "label": "СК",
                    "options": options(
                        Insurer.objects.order_by("insurer_name"),
                        "insurer_name",
                        params.insurer,
                    ),
                },
                {
                    "name": "type",
                    "label": "Вид",
                    "options": options(
                        InsuranceType.objects.order_by("name"), "name", params.type
                    ),
                },
                {
                    "name": "manager",
                    "label": "Менеджер",
                    "options": options(
                        LeasingManager.objects.order_by("name"),
                        "name",
                        params.manager,
                    ),
                },
            ],
        }


class AnalyticsTabView(AnalyticsV2Mixin, TemplateView):
    """Вкладка раздела. tab — ключ из TABS."""

    tab = "summary"

    def get_template_names(self):
        module = self._tab_module()
        return [
            f"analytics/v2/tabs/{self.tab}.html"
            if module
            else "analytics/v2/tabs/placeholder.html"
        ]

    def _tab_module(self):
        module_name = next(module for key, _, _, module in TABS if key == self.tab)
        return (
            import_module(f"apps.analytics.sections.{module_name}")
            if module_name
            else None
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.get_params()
        context.update(self.filter_context(params))
        context["tabs"] = [
            {
                "key": key,
                "title": title,
                "icon": icon,
                "url_name": tab_url_name(key),
                "active": key == self.tab,
                "ready": module is not None,
            }
            for key, title, icon, module in TABS
        ]
        context["tab"] = self.tab
        context["tab_title"] = next(title for key, title, *_ in TABS if key == self.tab)
        context["current_url_name"] = tab_url_name(self.tab)
        module = self._tab_module()
        context["show_period"] = getattr(module, "USES_PERIOD", True)
        context["show_as_of"] = getattr(module, "USES_AS_OF", False)
        if module:
            context["data"] = module.build(params, self.request.GET)
        return context


class DrilldownView(AnalyticsV2Mixin, TemplateView):
    """Список «под цифрой»: платежи или полисы величины, с выгрузкой в Excel."""

    template_name = "analytics/v2/list.html"
    max_rows_on_page = 2000

    def dispatch(self, request, *args, **kwargs):
        self.metric = drilldown.get_metric(kwargs["key"])
        if self.metric is None:
            raise Http404("Неизвестная величина")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.metric.build(self.get_params(), self.request.GET)

    def get(self, request, *args, **kwargs):
        if request.GET.get("format") == "xlsx":
            return self.export()
        return super().get(request, *args, **kwargs)

    def export(self):
        params = self.get_params()
        queryset = self.get_queryset()
        columns = drilldown.columns_for(self.metric.kind)
        rows = [row["cells"] for row in drilldown.list_rows(self.metric.kind, queryset)]
        return table_response(
            title=self.metric.title,
            headers=[label for _, label in columns],
            rows=rows,
            filename=f"analytics_{self.metric.key}_{params.today:%Y%m%d}.xlsx",
            subtitle=self._subtitle(params),
        )

    def _subtitle(self, params):
        return f"Период: {params.period_label}; срез на {params.as_of:%d.%m.%Y}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.get_params()
        queryset = self.get_queryset()
        rows = drilldown.list_rows(self.metric.kind, queryset)
        context.update(self.filter_context(params))
        context.update(
            {
                "metric": self.metric,
                "columns": [
                    label for _, label in drilldown.columns_for(self.metric.kind)
                ],
                "money_columns": [
                    index
                    for index, (name, _) in enumerate(
                        drilldown.columns_for(self.metric.kind)
                    )
                    if name in drilldown.MONEY_FIELDS
                ],
                "rows": rows[: self.max_rows_on_page],
                "rows_truncated": len(rows) > self.max_rows_on_page,
                "totals": drilldown.list_totals(self.metric.kind, queryset),
                "is_payments": self.metric.kind == drilldown.PAYMENTS,
                "export_query": self._export_query(),
            }
        )
        return context

    def _export_query(self):
        query = self.request.GET.copy()
        query["format"] = "xlsx"
        return query.urlencode()
