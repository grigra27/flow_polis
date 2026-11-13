"""Возврат из карточки к выборке в той же вкладке."""

from urllib.parse import urlsplit

from django.core.paginator import Paginator
from django.urls import reverse


class JournalPaginator(Paginator):
    def validate_number(self, number):
        # После правки последняя запись на последней странице может исчезнуть.
        if isinstance(number, int) and number > self.num_pages:
            return self.num_pages
        return super().validate_number(number)


def journal_origin(value):
    """Разрешаем только ссылки на два журнала, сохраняя запрос и якорь строки."""
    for name in ("policies:list", "policies:payments"):
        path = reverse(name)
        if value == path or value.startswith((path + "?", path + "#")):
            return value
    return ""


def card_params(params):
    origin = journal_origin(params.get("journal", ""))
    if origin:
        return {"journal": origin}
    summary = params.get("from_summary", "")
    if summary.isascii() and summary.isdecimal():
        result = {"from_summary": summary}
        if params.get("in_force") == "1":
            result["in_force"] = "1"
        return result
    return {}


def policy_card_url(policy_id, params):
    return reverse("policies:detail", args=[policy_id], query=card_params(params))


def journal_label(origin):
    if urlsplit(origin).path == reverse("policies:payments"):
        return "К журналу платежей"
    return "К журналу полисов"
