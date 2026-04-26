"""
Тесты единой утилиты apps.core.notifications.

Главное что проверяем:
  • VK отправляется ПЕРВЫМ — резервный 100%-канал не должен ждать TG.
  • Если Telegram падает (что нормально для сервера в РФ), VK всё равно идёт.
  • Если VK падает, Telegram всё равно пытается.
  • TELEGRAM_ENABLED=false корректно отключает только TG, не VK.
"""
from unittest.mock import patch

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
