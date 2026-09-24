"""
Тесты единой утилиты apps.core.notifications.

Главное что проверяем:
  • VK отправляется ПЕРВЫМ — резервный 100%-канал не должен ждать TG.
  • Если Telegram падает (что нормально для сервера в РФ), VK всё равно идёт.
  • Если VK падает, Telegram всё равно пытается.
  • TELEGRAM_ENABLED=false корректно отключает только TG, не VK.
"""
from unittest.mock import patch

import requests

import apps.core.notifications as notifications


def test_send_to_all_calls_vk_before_telegram(monkeypatch):
    """VK = 100% backup — должен отправляться ПЕРВЫМ, до TG."""
    call_order = []

    def fake_vk(text):
        call_order.append("vk")
        return True

    def fake_tg(text):
        call_order.append("tg")
        return True

    monkeypatch.setattr(notifications, "send_vk", fake_vk)
    monkeypatch.setattr(notifications, "send_telegram", fake_tg)

    result = notifications.send_to_all("hi")

    assert call_order == ["vk", "tg"], f"VK must be first; got {call_order}"
    assert result == {"vk": True, "telegram": True}


def test_send_to_all_vk_independent_of_telegram(monkeypatch):
    """Если TG упал — VK всё равно отправляется (резервный канал)."""
    monkeypatch.setattr(notifications, "send_vk", lambda text: True)
    monkeypatch.setattr(notifications, "send_telegram", lambda text: False)

    result = notifications.send_to_all("hi")

    assert result == {"vk": True, "telegram": False}


def test_send_to_all_telegram_independent_of_vk(monkeypatch):
    """Если VK упал — TG всё равно пробуется."""
    monkeypatch.setattr(notifications, "send_vk", lambda text: False)
    monkeypatch.setattr(notifications, "send_telegram", lambda text: True)

    result = notifications.send_to_all("hi")

    assert result == {"vk": False, "telegram": True}


def test_send_telegram_returns_false_when_disabled(monkeypatch):
    """TELEGRAM_ENABLED=false → не пытаемся отправить, возвращаем False."""

    # Мокаем decouple.config так чтобы вернуть TELEGRAM_ENABLED=False
    def fake_config(key, default=None, cast=None):
        if key == "TELEGRAM_ENABLED":
            return False
        return default

    monkeypatch.setattr(notifications, "config", fake_config)

    # Никаких реальных HTTP-запросов — если бы они были, urlopen упал бы
    assert notifications.send_telegram("hi") is False


def test_send_telegram_returns_false_when_no_token(monkeypatch):
    """Нет TELEGRAM_BOT_TOKEN → не пытаемся отправить."""

    def fake_config(key, default=None, cast=None):
        if key == "TELEGRAM_ENABLED":
            return True
        return default  # пустые токен/чат

    monkeypatch.setattr(notifications, "config", fake_config)

    assert notifications.send_telegram("hi") is False


def test_send_telegram_handles_network_error(monkeypatch):
    """URLError от Telegram (типичная ошибка из-за блокировки в РФ) → False, без падения."""
    from urllib.error import URLError

    def fake_config(key, default=None, cast=None):
        return {
            "TELEGRAM_ENABLED": True,
            "TELEGRAM_BOT_TOKEN": "x",
            "TELEGRAM_CHAT_ID": "y",
        }.get(key, default)

    def fake_urlopen(*args, **kwargs):
        raise URLError("Connection blocked (simulated)")

    monkeypatch.setattr(notifications, "config", fake_config)
    monkeypatch.setattr(notifications, "urlopen", fake_urlopen)

    # Не должно бросать исключение — caller'у достаточно False
    assert notifications.send_telegram("hi") is False


# ──────────────────────────────────────────────────────────────────
# Тесты TELEGRAM_SOCKS5_PROXY (2026-09-24): сервер в РФ, api.telegram.org
# заблокирован на уровне DPI — прямые urlopen-запросы уходят в таймаут.
# Когда прокси настроен, send_telegram() идёт через requests+proxies
# вместо urlopen; urlopen в этих тестах намеренно НЕ мокается — если бы
# код по ошибке пошёл через него, тест бы упал на реальном сетевом вызове.
# ──────────────────────────────────────────────────────────────────


def _proxy_config(overrides=None):
    values = {
        "TELEGRAM_ENABLED": True,
        "TELEGRAM_BOT_TOKEN": "x",
        "TELEGRAM_CHAT_ID": "y",
        "TELEGRAM_SOCKS5_PROXY": "127.0.0.1:1080",
    }
    if overrides:
        values.update(overrides)

    def fake(key, default=None, cast=None):
        return values.get(key, default)

    return fake


class _FakeRequestsResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data


def test_send_telegram_uses_proxy_and_not_urlopen_when_configured(monkeypatch):
    """TELEGRAM_SOCKS5_PROXY задан → requests.post с нужным proxies, urlopen
    не трогается вообще (иначе тест упал бы на реальном сетевом вызове)."""
    monkeypatch.setattr(notifications, "config", _proxy_config())

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("urlopen must not be called when a proxy is configured")

    monkeypatch.setattr(notifications, "urlopen", fail_urlopen)

    calls = []

    def fake_post(url, data=None, proxies=None, timeout=None):
        calls.append({"url": url, "data": data, "proxies": proxies})
        return _FakeRequestsResponse(200, {"ok": True})

    monkeypatch.setattr(notifications.requests, "post", fake_post)

    assert notifications.send_telegram("hi") is True
    assert len(calls) == 1
    assert calls[0]["proxies"] == {"https": "socks5h://127.0.0.1:1080"}
    assert calls[0]["url"] == "https://api.telegram.org/botx/sendMessage"
    assert calls[0]["data"]["text"] == "hi"


def test_send_telegram_via_proxy_returns_false_on_api_error(monkeypatch):
    """Telegram отвечает {"ok": false} через прокси → False, не исключение."""
    monkeypatch.setattr(notifications, "config", _proxy_config())
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **kw: _FakeRequestsResponse(200, {"ok": False, "error_code": 400}),
    )

    assert notifications.send_telegram("hi") is False


def test_send_telegram_via_proxy_handles_network_error(monkeypatch):
    """Туннель недоступен (прокси упал/не поднят) → False, без падения."""
    monkeypatch.setattr(notifications, "config", _proxy_config())

    def fake_post(*args, **kwargs):
        raise requests.exceptions.ConnectionError("SOCKS proxy unreachable")

    monkeypatch.setattr(notifications.requests, "post", fake_post)

    assert notifications.send_telegram("hi") is False


def test_send_telegram_via_proxy_handles_non_json_response(monkeypatch):
    """Прокси/сервер вернул не-JSON (например, HTML страницу ошибки) → False."""
    monkeypatch.setattr(notifications, "config", _proxy_config())
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **kw: _FakeRequestsResponse(200, None, text="<html>502</html>"),
    )

    assert notifications.send_telegram("hi") is False


def test_send_telegram_via_proxy_429_returns_false_by_default(monkeypatch):
    """429 через прокси, raise_on_rate_limit=False (default) → False."""
    monkeypatch.setattr(notifications, "config", _proxy_config())
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **kw: _FakeRequestsResponse(
            429, text='{"parameters":{"retry_after":5}}'
        ),
    )

    assert notifications.send_telegram("hi") is False


def test_send_telegram_via_proxy_429_raises_when_caller_asks(monkeypatch):
    """429 через прокси, raise_on_rate_limit=True → TelegramRateLimitError
    с retry_after из JSON body — тот же _parse_retry_after, что и в
    прямом (urlopen) пути, просто на requests.Response вместо HTTPError."""
    monkeypatch.setattr(notifications, "config", _proxy_config())
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **kw: _FakeRequestsResponse(
            429, text='{"parameters":{"retry_after":42}}'
        ),
    )

    import pytest

    with pytest.raises(notifications.TelegramRateLimitError) as exc_info:
        notifications.send_telegram("hi", raise_on_rate_limit=True)
    assert exc_info.value.retry_after == 42


def test_send_telegram_no_proxy_still_uses_urlopen(monkeypatch):
    """TELEGRAM_SOCKS5_PROXY не задан (default) — прежнее поведение
    неизменно, requests.post не вызывается вообще."""

    def fake_config(key, default=None, cast=None):
        return {
            "TELEGRAM_ENABLED": True,
            "TELEGRAM_BOT_TOKEN": "x",
            "TELEGRAM_CHAT_ID": "y",
        }.get(key, default)

    monkeypatch.setattr(notifications, "config", fake_config)

    def fail_post(*args, **kwargs):
        raise AssertionError("requests.post must not be called without a proxy")

    monkeypatch.setattr(notifications.requests, "post", fail_post)

    class _FakeUrlopenCtx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"ok": true}'

    monkeypatch.setattr(notifications, "urlopen", lambda *a, **kw: _FakeUrlopenCtx())

    assert notifications.send_telegram("hi") is True


def test_trim_with_middle_ellipsis_keeps_tail():
    """Обрезание длинного текста сохраняет конец (важно для traceback)."""
    long = "START-" + ("X" * 500) + "-FINAL"
    out = notifications.trim_with_middle_ellipsis(
        long, max_length=80, marker="|...|", tail_ratio=0.8
    )
    assert len(out) <= 80
    assert out.startswith("START-")
    assert out.endswith("-FINAL")
    assert "|...|" in out


def test_send_vk_delegates_to_send_vk_message(monkeypatch):
    """notifications.send_vk — тонкая обёртка над vk_handler.send_vk_message."""
    call_args = []

    def fake_send(text):
        call_args.append(text)
        return True

    monkeypatch.setattr(notifications, "send_vk_message", fake_send)

    assert notifications.send_vk("hello") is True
    assert call_args == ["hello"]


def test_check_rate_limit_fail_open_when_redis_unavailable(monkeypatch):
    """Если Redis недоступен — fail-open (возвращаем True). Лучше дубль чем тишина."""
    monkeypatch.setattr(notifications, "_get_redis", lambda: None)
    # Также сбрасываем кеш клиента
    notifications._redis_client = None

    assert notifications.check_rate_limit("any_scope", max_per_hour=10) is True


def test_check_rate_limit_blocks_after_max(monkeypatch):
    """После max_per_hour подряд возвращает False."""
    # Имитируем INCR через простой counter
    counter = {"value": 0}

    class FakeRedis:
        def incr(self, key):
            counter["value"] += 1
            return counter["value"]

        def expire(self, key, ttl):
            pass

    monkeypatch.setattr(notifications, "_get_redis", lambda: FakeRedis())

    # Первые 5 вызовов проходят
    for i in range(5):
        assert notifications.check_rate_limit("test", max_per_hour=5) is True
    # 6-й — упёрлись в лимит
    assert notifications.check_rate_limit("test", max_per_hour=5) is False


def test_check_rate_limit_fail_open_when_redis_raises(monkeypatch):
    """Если INCR упал (например, redis-broker во flux) — fail-open."""

    class BrokenRedis:
        def incr(self, key):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(notifications, "_get_redis", lambda: BrokenRedis())

    # Не падает, возвращает True
    assert notifications.check_rate_limit("test", max_per_hour=10) is True


# ──────────────────────────────────────────────────────────────────
# Тесты HTTP 429 retry (PLAN 11.3)
# ──────────────────────────────────────────────────────────────────


def _http_error_429(body_json: str = "", header_retry_after: str = None):
    """Создаёт HTTPError с кодом 429 и заданными body+header."""
    from io import BytesIO
    from urllib.error import HTTPError

    headers = {}
    if header_retry_after is not None:
        headers["Retry-After"] = header_retry_after
    body_bytes = body_json.encode("utf-8") if body_json else b""
    return HTTPError(
        url="https://api.telegram.org/...",
        code=429,
        msg="Too Many Requests",
        hdrs=headers,
        fp=BytesIO(body_bytes),
    )


def test_send_telegram_429_raises_when_caller_asks(monkeypatch):
    """raise_on_rate_limit=True → 429 поднимает TelegramRateLimitError."""

    def fake_config(key, default=None, cast=None):
        return {
            "TELEGRAM_ENABLED": True,
            "TELEGRAM_BOT_TOKEN": "x",
            "TELEGRAM_CHAT_ID": "y",
        }.get(key, default)

    body = '{"ok":false,"error_code":429,"parameters":{"retry_after":42}}'

    def fake_urlopen(*args, **kwargs):
        raise _http_error_429(body_json=body)

    monkeypatch.setattr(notifications, "config", fake_config)
    monkeypatch.setattr(notifications, "urlopen", fake_urlopen)

    import pytest

    with pytest.raises(notifications.TelegramRateLimitError) as exc_info:
        notifications.send_telegram("hi", raise_on_rate_limit=True)
    assert exc_info.value.retry_after == 42


def test_send_telegram_429_returns_false_by_default(monkeypatch):
    """raise_on_rate_limit=False (default) → 429 = False, не падает."""

    def fake_config(key, default=None, cast=None):
        return {
            "TELEGRAM_ENABLED": True,
            "TELEGRAM_BOT_TOKEN": "x",
            "TELEGRAM_CHAT_ID": "y",
        }.get(key, default)

    def fake_urlopen(*args, **kwargs):
        raise _http_error_429(body_json='{"ok":false,"parameters":{"retry_after":5}}')

    monkeypatch.setattr(notifications, "config", fake_config)
    monkeypatch.setattr(notifications, "urlopen", fake_urlopen)

    # Default raise_on_rate_limit=False — exception проглочен, возвращаем False
    assert notifications.send_telegram("hi") is False


def test_parse_retry_after_prefers_json_body():
    """retry_after из JSON body имеет приоритет над Retry-After header."""
    err = _http_error_429(
        body_json='{"parameters":{"retry_after":99}}',
        header_retry_after="11",
    )
    assert (
        notifications._parse_retry_after(err, '{"parameters":{"retry_after":99}}') == 99
    )


def test_parse_retry_after_falls_back_to_header():
    """Если в body нет retry_after — берём из Retry-After header."""
    err = _http_error_429(body_json="", header_retry_after="33")
    assert notifications._parse_retry_after(err, "") == 33


def test_parse_retry_after_default_when_nothing_present():
    """Нет ни в body ни в header — default 60."""
    err = _http_error_429(body_json="", header_retry_after=None)
    assert notifications._parse_retry_after(err, "") == 60


# ──────────────────────────────────────────────────────────────────
# Тесты VK file upload (PLAN 11.5)
# ──────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _vk_config_enabled():
    """Helper: imitate decouple.config returning enabled VK + creds."""

    def fake(key, default=None, cast=None):
        return {
            "VK_ENABLED": True,
            "VK_COMMUNITY_TOKEN": "vk-token",
            "VK_USER_ID": "12345",
        }.get(key, default)

    return fake


def test_send_vk_file_full_4_step_flow(monkeypatch, tmp_path):
    """Успешный 4-шаговый upload: getUploadServer → upload → save → send."""
    monkeypatch.setattr(notifications, "config", _vk_config_enabled())

    test_file = tmp_path / "report.xlsx"
    test_file.write_bytes(b"fake-excel-content")

    # Каждому из 4 POST'ов соответствует свой ответ
    responses = iter(
        [
            _FakeResponse({"response": {"upload_url": "https://upload.vk/abc"}}),
            _FakeResponse({"file": "file-token-xyz"}),
            _FakeResponse(
                {"response": [{"owner_id": -111, "id": 222}]}
            ),  # docs.save list-форма
            _FakeResponse({"response": 999}),  # messages.send: ID нового сообщения
        ]
    )
    posts = []

    def fake_post(url, **kwargs):
        posts.append(url)
        return next(responses)

    monkeypatch.setattr(notifications.requests, "post", fake_post)

    assert notifications.send_vk_file(str(test_file), caption="Test backup") is True
    # Проверяем что все 4 шага были вызваны
    assert len(posts) == 4
    assert "docs.getMessagesUploadServer" in posts[0]
    assert posts[1] == "https://upload.vk/abc"
    assert "docs.save" in posts[2]
    assert "messages.send" in posts[3]


def test_send_vk_file_supports_dict_response_from_docs_save(monkeypatch, tmp_path):
    """docs.save может вернуть response.doc.{owner_id,id} вместо list."""
    monkeypatch.setattr(notifications, "config", _vk_config_enabled())

    test_file = tmp_path / "doc.pdf"
    test_file.write_bytes(b"x")

    responses = iter(
        [
            _FakeResponse({"response": {"upload_url": "https://upload.vk/xyz"}}),
            _FakeResponse({"file": "tok"}),
            # ← объектная форма
            _FakeResponse({"response": {"doc": {"owner_id": -42, "id": 7}}}),
            _FakeResponse({"response": 1}),
        ]
    )
    monkeypatch.setattr(
        notifications.requests, "post", lambda *a, **kw: next(responses)
    )

    assert notifications.send_vk_file(str(test_file)) is True


def test_send_vk_file_returns_false_when_disabled(monkeypatch, tmp_path):
    """VK_ENABLED=false → не пытаемся отправить."""

    def fake(key, default=None, cast=None):
        if key == "VK_ENABLED":
            return False
        return default

    monkeypatch.setattr(notifications, "config", fake)

    test_file = tmp_path / "x.txt"
    test_file.write_bytes(b"x")

    # Мокаем requests чтобы убедиться что НЕ вызывается
    calls = []
    monkeypatch.setattr(
        notifications.requests, "post", lambda *a, **kw: calls.append(a)
    )

    assert notifications.send_vk_file(str(test_file)) is False
    assert calls == []  # ни одного HTTP-запроса


def test_send_vk_file_returns_false_when_file_missing(monkeypatch):
    """Файл не существует → False, без попытки отправки."""
    monkeypatch.setattr(notifications, "config", _vk_config_enabled())

    calls = []
    monkeypatch.setattr(
        notifications.requests, "post", lambda *a, **kw: calls.append(a)
    )

    assert notifications.send_vk_file("/nonexistent/path.xlsx") is False
    assert calls == []


def test_send_vk_file_handles_step1_api_error(monkeypatch, tmp_path):
    """VK API возвращает {error: ...} на первом шаге → False, без падения."""
    monkeypatch.setattr(notifications, "config", _vk_config_enabled())

    test_file = tmp_path / "x.txt"
    test_file.write_bytes(b"x")

    # Шаг 1 возвращает error — дальше шагов быть не должно
    posts = []

    def fake_post(url, **kwargs):
        posts.append(url)
        return _FakeResponse({"error": {"error_code": 5, "error_msg": "Auth fail"}})

    monkeypatch.setattr(notifications.requests, "post", fake_post)

    assert notifications.send_vk_file(str(test_file)) is False
    assert len(posts) == 1  # только первый шаг


def test_send_vk_file_handles_network_error(monkeypatch, tmp_path):
    """RequestException на любом шаге → False, без падения."""
    monkeypatch.setattr(notifications, "config", _vk_config_enabled())

    test_file = tmp_path / "x.txt"
    test_file.write_bytes(b"x")

    def fake_post(*args, **kwargs):
        raise notifications.requests.ConnectionError("network down")

    monkeypatch.setattr(notifications.requests, "post", fake_post)

    assert notifications.send_vk_file(str(test_file)) is False
