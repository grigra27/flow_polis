"""Серверный клиент акцептов ЗС. Адрес берётся только из настроек."""
from decimal import Decimal
import re
from urllib.parse import urlsplit

import requests
from django.conf import settings


class FlowError(ValueError):
    pass


def _request(method, path, **kwargs):
    base = settings.FLOW_ZS_BASE_URL.rstrip("/")
    parsed = urlsplit(base)
    local_http = (
        settings.DEBUG
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if not settings.FLOW_HANDOFF_ENABLED or not settings.FLOW_SERVICE_TOKEN:
        raise FlowError("Связь с ЗС выключена.")
    if (
        (parsed.scheme != "https" and not local_http)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise FlowError("Не настроен адрес сервера ЗС.")
    try:
        response = requests.request(
            method,
            base + path,
            headers={"Authorization": "Bearer " + settings.FLOW_SERVICE_TOKEN},
            timeout=(3, 6),
            allow_redirects=False,
            **kwargs,
        )
    except requests.RequestException:
        raise FlowError("Сервер ЗС недоступен. Повторите попытку позже.") from None
    if response.status_code in (404, 409, 410):
        raise FlowError(
            "Акцепт или код перехода больше недоступен. Откройте сделку в ЗС повторно."
        )
    if response.status_code != 200:
        raise FlowError("Сервер ЗС не подтвердил запрос. Повторите попытку позже.")
    try:
        snapshot = response.json()["snapshot"]
        _validate_snapshot(snapshot)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise FlowError(
            "Получены некорректные данные свода. Откройте сделку в ЗС."
        ) from None
    return snapshot


# ЗС допускает 10 лет страхования, до 12 взносов за год.
MAX_YEARS = 10
MAX_INSTALLMENTS = 12
MAX_GROUP_SIZE = 1000


def _integer(value, upper):
    return type(value) is int and 1 <= value <= upper


def _money(value, *, positive):
    # DecimalField(max_digits=15, decimal_places=2); экспоненциальная запись
    # не входит в договор v1 и может вызвать переполнение при делении.
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{1,13}(?:\.[0-9]{1,2})?", value
    ):
        raise ValueError
    if positive and Decimal(value) == 0:
        raise ValueError


def _validate_snapshot(data):
    if (
        not isinstance(data, dict)
        or data["source"] != "zs"
        or not _integer(data["schema_version"], 1)
    ):
        raise ValueError
    if not all(_integer(data[k], 2**63 - 1) for k in ("summary_id", "request_id")):
        raise ValueError
    if not _integer(data["source_object_count"], MAX_GROUP_SIZE):
        raise ValueError
    if not isinstance(data["revision"], str) or not 0 < len(data["revision"]) <= 128:
        raise ValueError
    variants, chosen, offers = (
        data["available_variants"],
        data["variant"],
        data["offers"],
    )
    if (
        not isinstance(variants, list)
        or not all(_integer(v, 2) for v in variants)
        or len(set(variants)) != len(variants)
    ):
        raise ValueError
    if chosen is not None and not (_integer(chosen, 2) and chosen in variants):
        raise ValueError
    if (
        not isinstance(offers, list)
        or len(offers) > MAX_YEARS
        or bool(offers) != (chosen is not None)
    ):
        raise ValueError
    for field in (
        "dfa_number",
        "client_name",
        "client_inn",
        "branch",
        "insurance_type",
        "selected_company",
        "insured_party",
        "manager_name",
        "property_description",
    ):
        if not isinstance(data[field], str):
            raise ValueError
    seen_years = set()
    for row in offers:
        year = row["year"]
        if (
            not _integer(year, MAX_YEARS)
            or year in seen_years
            or not _integer(row["installments"], MAX_INSTALLMENTS)
        ):
            raise ValueError
        seen_years.add(year)
        for field in ("premium", "insurance_sum", "franchise"):
            _money(row[field], positive=field != "franchise")


def exchange_ticket(code):
    if not isinstance(code, str) or not code or len(code) > 256:
        raise FlowError("Недействительный код перехода из ЗС.")
    return _request("POST", "/internal/flow/v1/exchange/", json={"code": code})


def fetch_snapshot(summary_id):
    if not isinstance(summary_id, int) or summary_id < 1:
        raise FlowError("Некорректный номер свода.")
    snapshot = _request("GET", f"/internal/flow/v1/summaries/{summary_id}/")
    if snapshot["summary_id"] != summary_id:
        raise FlowError("ЗС вернул другой свод.")
    return snapshot
