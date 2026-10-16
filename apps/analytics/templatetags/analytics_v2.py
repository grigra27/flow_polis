from datetime import date
from urllib.parse import urlencode

from django import template
from django.urls import reverse
from django.utils.dateparse import parse_date

from apps.analytics.filters import DIMENSIONS

register = template.Library()


def split_overrides(params, kwargs):
    """Делит аргументы тега на поля AnalyticsParams (overrides) и opts величины.

    Разрез (branch/insurer/type/manager) из строки таблицы заменяет фильтр
    целиком; явные даты периода сбрасывают пресет.
    """
    overrides, opts = {}, {}
    for name, value in kwargs.items():
        if value in (None, ""):
            continue
        if name in DIMENSIONS:
            overrides[name] = value if isinstance(value, list) else [int(value)]
        elif name in ("date_from", "date_to", "as_of"):
            overrides[name] = value if isinstance(value, date) else parse_date(value)
        elif name in ("preset", "with_osago"):
            overrides[name] = value
        else:
            opts[name] = value
    if (
        "date_from" in overrides or "date_to" in overrides
    ) and "preset" not in overrides:
        overrides["preset"] = None
    return overrides, opts


@register.simple_tag(takes_context=True)
def drill_url(context, key, **kwargs):
    """Ссылка на список «под цифрой» с текущими фильтрами раздела.

    {% drill_url 'earned' month='2026-03' insurer=row.insurer_id %}
    """
    params = context["params"]
    overrides, opts = split_overrides(params, kwargs)
    items = params.query_items(**overrides)
    items.extend(opts.items())
    url = reverse("analytics:v2_list", args=[key])
    query = urlencode(items)
    return f"{url}?{query}" if query else url


@register.simple_tag(takes_context=True)
def tab_url(context, url_name, **overrides):
    """Ссылка на вкладку с текущими фильтрами раздела."""
    query = context["params"].querystring(**overrides)
    url = reverse(url_name)
    return f"{url}?{query}" if query else url


@register.filter
def money_short(value):
    """1 234 567 → «1,23 млн»; меньше миллиона — «123 тыс.»."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    sign = "−" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000:
        return f"{sign}{number / 1_000_000:.2f} млн".replace(".", ",")
    if number >= 1_000:
        return f"{sign}{number / 1_000:.0f} тыс."
    return f"{sign}{number:.0f}"


def _plural_form(value, forms):
    one, few, many = forms.split(",")
    number = abs(int(value))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


@register.filter
def plural(value, forms):
    """{{ n|plural:"платёж,платежа,платежей" }} → «3 платежа»."""
    try:
        return f"{value} {_plural_form(value, forms)}"
    except (TypeError, ValueError):
        return value


@register.filter
def plural_word(value, forms):
    """Только слово: {{ n|plural_word:"платёж,платежа,платежей" }} → «платежа»."""
    try:
        return _plural_form(value, forms)
    except (TypeError, ValueError):
        return forms.split(",")[-1]
