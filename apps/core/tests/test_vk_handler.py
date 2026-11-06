"""
Тесты apps.core.vk_handler.send_vk_message — низкоуровневой VK-отправки.

Отдельный файл (а не test_notifications.py), потому что здесь проверяется
поведение конкретно этого модуля: атрибуция источника (2026-09-24) и то,
что обрезание по лимиту VK учитывает уже добавленный префикс. Маршрутизацию
VK/Telegram (какой канал первый, независимость друг от друга) покрывает
test_notifications.py.
"""
from urllib.parse import parse_qs
from unittest.mock import patch

import apps.core.vk_handler as vk_handler


def _vk_config_enabled():
    values = {
        "VK_ENABLED": True,
        "VK_COMMUNITY_TOKEN": "vk-token",
        "VK_USER_ID": "12345",
    }

    def fake(key, default=None, cast=None):
        return values.get(key, default)

    return fake


class _FakeResponse:
    """Минимальная замена ответа urlopen — context manager с .read()."""

    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _sent_message(monkeypatch, text):
    """Прогоняет text через send_vk_message и возвращает декодированное
    поле message из тела реального HTTP-запроса, который ушёл бы в VK API."""
    monkeypatch.setattr(vk_handler, "config", _vk_config_enabled())

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = request.data.decode("utf-8")
        return _FakeResponse('{"response": 1}')

    monkeypatch.setattr(vk_handler, "urlopen", fake_urlopen)

    assert vk_handler.send_vk_message(text) is True
    return parse_qs(captured["body"])["message"][0]


def test_send_vk_message_prepends_attribution_prefix(monkeypatch):
    """Каждое VK-сообщение начинается с метки проекта — в этот же диалог
    шлют сообщения и другие проекты, без метки источник не понять."""
    sent = _sent_message(monkeypatch, "Тестовое сообщение")

    assert sent == f"{vk_handler.VK_ATTRIBUTION_PREFIX}\n\nТестовое сообщение"


def test_send_vk_message_truncation_accounts_for_prefix(monkeypatch):
    """Обрезка по VK_MAX_MESSAGE_LENGTH применяется ПОСЛЕ добавления
    префикса — иначе итоговое сообщение может превысить лимит VK API."""
    long_text = "X" * vk_handler.VK_MAX_MESSAGE_LENGTH
    sent = _sent_message(monkeypatch, long_text)

    assert len(sent) == vk_handler.VK_MAX_MESSAGE_LENGTH
    assert sent.startswith(vk_handler.VK_ATTRIBUTION_PREFIX)


def test_long_vk_error_keeps_attribution_context_and_exception_tail(monkeypatch):
    tail = "IntegrityError: duplicate policy number"
    text = "Request context\n" + "trace frame\n" * 1000 + tail

    sent = _sent_message(monkeypatch, text)

    assert len(sent) == vk_handler.VK_MAX_MESSAGE_LENGTH
    assert sent.startswith(vk_handler.VK_ATTRIBUTION_PREFIX + "\n\nRequest context")
    assert sent.endswith(tail)


def test_vk_random_ids_use_os_entropy_within_nonzero_int32(monkeypatch):
    """Copied/reseeded application PRNG state must not replay outgoing IDs."""
    monkeypatch.setattr(vk_handler, "config", _vk_config_enabled())
    draws = iter([0, 2**31 - 2])
    bounds = []
    sent_ids = []

    def entropy(bound):
        bounds.append(bound)
        return next(draws)

    def fake_urlopen(request, timeout=None):
        sent_ids.append(int(parse_qs(request.data.decode())["random_id"][0]))
        return _FakeResponse('{"response": 1}')

    monkeypatch.setattr(vk_handler.secrets, "randbelow", entropy)
    monkeypatch.setattr(vk_handler, "urlopen", fake_urlopen)
    with patch("random.randint", return_value=42):
        assert vk_handler.send_vk_message("first") is True
        assert vk_handler.send_vk_message("second") is True

    assert bounds == [2**31 - 1, 2**31 - 1]
    assert sent_ids == [1, 2**31 - 1]
