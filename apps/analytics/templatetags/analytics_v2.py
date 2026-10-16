from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def drill_url(context, key, **opts):
    """Ссылка на список «под цифрой» с текущими фильтрами раздела."""
    params = context["params"]
    items = params.query_items()
    items.extend(
        (name, value) for name, value in opts.items() if value not in (None, "")
    )
    from urllib.parse import urlencode

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
