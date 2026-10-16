"""
Параметры Аналитики 2.0: один объект фильтров на весь раздел.

Фильтры живут в GET-параметрах, поэтому любую вкладку и любой список «под
цифрой» можно сохранить ссылкой. См. docs/analytics-2.0-plan.md, §2 и §5.

Базовые выборки (policies / payments) уже учитывают разрезы (филиал, СК, вид,
менеджер), ОСАГО и исключение полисов без участия брокера. Даты периода
базовые выборки НЕ режут: у каждой величины своя дата (акт, срок платежа,
начало полиса), поэтому период применяет сама величина.
"""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import List, Optional
from urllib.parse import urlencode

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date

PERIOD_PRESETS = [
    ("year", "Год"),
    ("prev_year", "Прошлый год"),
    ("quarter", "Квартал"),
    ("month", "Месяц"),
    ("12m", "12 мес."),
]

# Разрезы: GET-параметр → поле Policy.
DIMENSIONS = {
    "branch": "branch_id",
    "insurer": "insurer_id",
    "type": "insurance_type_id",
    "manager": "leasing_manager_id",
}


def preset_range(preset: str, today: date):
    """Границы периода для пресета; None — неизвестный пресет."""
    if preset == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if preset == "prev_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if preset == "quarter":
        first_month = (today.month - 1) // 3 * 3 + 1
        start = date(today.year, first_month, 1)
        return start, _month_end(start, months=3)
    if preset == "month":
        start = today.replace(day=1)
        return start, _month_end(start, months=1)
    if preset == "12m":
        start = date(today.year - 1, today.month, 1)
        start = _add_months(start, 1)
        return start, _month_end(today.replace(day=1), months=1)
    return None


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _month_end(month_start: date, months: int) -> date:
    return _add_months(month_start, months) - timedelta(days=1)


def _int_list(values) -> List[int]:
    result = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


@dataclass
class AnalyticsParams:
    today: date
    date_from: date
    date_to: date
    as_of: date
    preset: Optional[str] = "year"
    branch: List[int] = field(default_factory=list)
    insurer: List[int] = field(default_factory=list)
    type: List[int] = field(default_factory=list)
    manager: List[int] = field(default_factory=list)
    with_osago: bool = False

    @classmethod
    def from_query(cls, query, today: Optional[date] = None) -> "AnalyticsParams":
        """Разбор GET-параметров. Некорректные значения молча игнорируются."""
        today = today or timezone.localdate()
        preset = query.get("period") or None
        date_from = parse_date(query.get("from") or "")
        date_to = parse_date(query.get("to") or "")

        if date_from or date_to:
            preset = None
            date_from = date_from or date(today.year, 1, 1)
            date_to = date_to or date(today.year, 12, 31)
            if date_to < date_from:
                date_from, date_to = date_to, date_from
        else:
            preset = preset if preset_range(preset or "", today) else "year"
            date_from, date_to = preset_range(preset, today)

        return cls(
            today=today,
            date_from=date_from,
            date_to=date_to,
            as_of=parse_date(query.get("as_of") or "") or today,
            preset=preset,
            branch=_int_list(query.getlist("branch")),
            insurer=_int_list(query.getlist("insurer")),
            type=_int_list(query.getlist("type")),
            manager=_int_list(query.getlist("manager")),
            with_osago=query.get("osago") == "1",
        )

    # --- выборки -----------------------------------------------------------

    def _dimension_q(self, prefix: str = "") -> Q:
        q = Q()
        for name, field_name in DIMENSIONS.items():
            ids = getattr(self, name)
            if ids:
                q &= Q(**{f"{prefix}{field_name}__in": ids})
        if not self.with_osago:
            q &= Q(**{f"{prefix}insurance_type__is_osago": False})
        return q

    def osago_policies(self) -> QuerySet:
        """Полисы ОСАГО по разрезам (переключатель ОСАГО не влияет), с участием брокера."""
        from apps.policies.models import Policy

        q = Q(insurance_type__is_osago=True, broker_participation=True)
        for name, field_name in DIMENSIONS.items():
            if getattr(self, name):
                q &= Q(**{f"{field_name}__in": getattr(self, name)})
        return Policy.objects.filter(q)

    def all_policies(self) -> QuerySet:
        """Полисы по разрезам и ОСАГО, включая полисы без участия брокера."""
        from apps.policies.models import Policy

        return Policy.objects.filter(self._dimension_q())

    def all_payments(self) -> QuerySet:
        """Платежи по разрезам и ОСАГО, включая полисы без участия брокера."""
        from apps.policies.models import PaymentSchedule

        return PaymentSchedule.objects.filter(self._dimension_q("policy__"))

    def policies(self) -> QuerySet:
        """Полисы для аналитики: без полисов «без участия брокера»."""
        return self.all_policies().filter(broker_participation=True)

    def payments(self) -> QuerySet:
        """Платежи для аналитики: без полисов «без участия брокера»."""
        return self.all_payments().filter(policy__broker_participation=True)

    def non_broker_policies(self) -> QuerySet:
        """Полисы без участия брокера — показываются отдельной строкой."""
        return self.all_policies().filter(broker_participation=False)

    def non_broker_payments(self) -> QuerySet:
        return self.all_payments().filter(policy__broker_participation=False)

    # --- ссылки ------------------------------------------------------------

    @property
    def has_dimension_filters(self) -> bool:
        return any(getattr(self, name) for name in DIMENSIONS)

    def query_items(self, **overrides) -> list:
        """Пары (ключ, значение) для URL; overrides заменяют поля целиком."""
        params = replace(self, **overrides) if overrides else self
        items = []
        if params.preset:
            if params.preset != "year":
                items.append(("period", params.preset))
        else:
            items.append(("from", params.date_from.isoformat()))
            items.append(("to", params.date_to.isoformat()))
        if params.as_of != params.today:
            items.append(("as_of", params.as_of.isoformat()))
        for name in DIMENSIONS:
            items.extend((name, value) for value in getattr(params, name))
        if params.with_osago:
            items.append(("osago", "1"))
        return items

    def querystring(self, **overrides) -> str:
        return urlencode(self.query_items(**overrides))

    def preset_links(self) -> list:
        """Пресеты периода для панели фильтров (разрезы сохраняются)."""
        links = []
        for key, label in PERIOD_PRESETS:
            start, end = preset_range(key, self.today)
            query = self.querystring(preset=key, date_from=start, date_to=end)
            links.append(
                {
                    "key": key,
                    "label": label,
                    "query": query,
                    "active": key == self.preset,
                }
            )
        return links

    @property
    def period_label(self) -> str:
        return f"{self.date_from:%d.%m.%Y} – {self.date_to:%d.%m.%Y}"
