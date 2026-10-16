"""
«Список под цифрой»: каждая цифра Аналитики 2.0 — ссылка на платежи или
полисы, из которых она сложилась.

Величина регистрируется один раз (@metric) и возвращает queryset. Тот же
queryset используют и вкладки (через resolve), и список, поэтому цифра и
список совпадают по построению.

Дополнительные параметры величины (месяц, корзина возраста, id СК…) приходят
в GET вместе с фильтрами раздела и передаются функции как opts.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from django.db.models import Count, DecimalField, QuerySet, Sum
from django.db.models.functions import Coalesce

from .filters import AnalyticsParams

PAYMENTS = "payments"
POLICIES = "policies"

ZERO = Decimal("0")


@dataclass(frozen=True)
class Metric:
    key: str
    title: str
    kind: str  # PAYMENTS | POLICIES
    build: Callable[[AnalyticsParams, Dict[str, str]], QuerySet]
    note: str = ""


METRICS: Dict[str, Metric] = {}


def metric(key: str, title: str, kind: str, note: str = ""):
    """Регистрирует величину для списка «под цифрой»."""

    def decorator(func):
        if key in METRICS:
            raise ValueError(f"Величина {key} уже зарегистрирована")
        METRICS[key] = Metric(key=key, title=title, kind=kind, build=func, note=note)
        return func

    return decorator


def get_metric(key: str) -> Optional[Metric]:
    _load_registries()
    return METRICS.get(key)


def resolve(key: str, params: AnalyticsParams, opts=None) -> QuerySet:
    """Queryset величины — для вкладок и для списка."""
    found = get_metric(key)
    if found is None:
        raise KeyError(key)
    return found.build(params, dict(opts or {}))


def _load_registries():
    # Величины объявлены в модулях вкладок; импорт регистрирует их.
    from .sections import registry  # noqa: F401


# --- колонки списков ----------------------------------------------------------

PAYMENT_COLUMNS = [
    ("policy__policy_number", "Полис"),
    ("policy__dfa_number", "ДФА"),
    ("policy__client__client_name", "Клиент"),
    ("policy__insurer__insurer_name", "СК"),
    ("policy__branch__branch_name", "Филиал"),
    ("policy__insurance_type__name", "Вид"),
    ("year_number", "Год"),
    ("installment_number", "Взнос"),
    ("due_date", "Дата платежа"),
    ("amount", "Премия"),
    ("kv_rub", "КВ"),
    ("paid_date", "Оплачен"),
    ("insurer_date", "Акт СК"),
]

POLICY_COLUMNS = [
    ("policy_number", "Полис"),
    ("dfa_number", "ДФА"),
    ("client__client_name", "Клиент"),
    ("insurer__insurer_name", "СК"),
    ("branch__branch_name", "Филиал"),
    ("insurance_type__name", "Вид"),
    ("leasing_manager__name", "Менеджер"),
    ("start_date", "Начало"),
    ("end_date", "Окончание"),
    ("termination_date", "Расторжение"),
    ("dfa_deactivation_date", "ДФА закрыт"),
]

MONEY_FIELDS = {"amount", "kv_rub"}


def columns_for(kind: str):
    return PAYMENT_COLUMNS if kind == PAYMENTS else POLICY_COLUMNS


def list_rows(kind: str, queryset: QuerySet) -> List[dict]:
    """Строки списка: значения колонок + id полиса для ссылки на карточку."""
    columns = columns_for(kind)
    policy_id_field = "policy_id" if kind == PAYMENTS else "id"
    order = (
        ["due_date", "policy__policy_number", "year_number", "installment_number"]
        if kind == PAYMENTS
        else ["end_date", "policy_number"]
    )
    values = queryset.order_by(*order).values(
        policy_id_field, *[name for name, _ in columns]
    )
    return [
        {
            "policy_id": row[policy_id_field],
            "cells": [row[name] for name, _ in columns],
        }
        for row in values
    ]


def list_totals(kind: str, queryset: QuerySet) -> dict:
    money = DecimalField(max_digits=15, decimal_places=2)
    if kind == PAYMENTS:
        return queryset.aggregate(
            count=Count("id"),
            policies=Count("policy", distinct=True),
            premium=Coalesce(Sum("amount"), ZERO, output_field=money),
            commission=Coalesce(Sum("kv_rub"), ZERO, output_field=money),
        )
    return {"count": queryset.count()}
