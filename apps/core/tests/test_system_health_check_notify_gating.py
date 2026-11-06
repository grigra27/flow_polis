"""
Тесты уведомлений system_health_check (2026-09-24): раньше cron слал одно
и то же предупреждение каждые 30 минут, пока проблему не устраняли — один
незамеченный сбой на несколько часов превращался в десятки одинаковых
сообщений в VK/Telegram. Теперь уведомляем только при смене overall_status
относительно того, о котором уведомили в прошлый раз (хранится в Redis —
cron дёргает команду новым процессом на каждый тик, in-memory состояние
между ними не переживает).

Что проверяем:
  • _resolve_notify_decision — чистая логика решения (без Redis);
  • _get_last_notified_status / _set_last_notified_status — round-trip
    через фейковый Redis-клиент, и fail-open (None), когда Redis недоступен.
"""
import logging
from io import StringIO

import pytest

from apps.core.management.commands import system_health_check as health_module
from apps.core.management.commands.system_health_check import Command


class _FakeRedis:
    """Минимальная замена redis-клиента: только то, что использует команда."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        value = self.store.get(key)
        return value.encode("utf-8") if value is not None else None

    def set(self, key, value):
        self.store[key] = value


def _patch_redis(monkeypatch, client):
    """Подменяет apps.core.notifications._get_redis — команда импортирует
    его лениво (inline import) прямо в месте использования."""
    import apps.core.notifications as notifications

    monkeypatch.setattr(notifications, "_get_redis", lambda: client)


def test_notify_always_ignores_history(monkeypatch):
    """--notify-always шлёт всегда, даже если статус не менялся."""
    command = Command()
    monkeypatch.setattr(command, "_get_last_notified_status", lambda: "healthy")

    assert command._resolve_notify_decision("healthy", True, True) is True


def test_not_requested_never_notifies():
    """Ни --notify-telegram, ни --notify-vk не переданы — решение не важно."""
    command = Command()

    assert command._resolve_notify_decision("critical", False, False) is False


def test_no_history_stays_silent_on_healthy(monkeypatch):
    """Первый прогон вообще (или Redis недоступен) — прежнее поведение по
    умолчанию: healthy молчит."""
    command = Command()
    monkeypatch.setattr(command, "_get_last_notified_status", lambda: None)

    assert command._resolve_notify_decision("healthy", True, False) is False


def test_no_history_notifies_once_on_first_problem(monkeypatch):
    """Первая же проблема без истории — уведомляем (нужно узнать о ней)."""
    command = Command()
    monkeypatch.setattr(command, "_get_last_notified_status", lambda: None)

    assert command._resolve_notify_decision("warning", True, False) is True


def test_unchanged_status_does_not_renotify(monkeypatch):
    """Тот же самый статус, что и в прошлом уведомлении, — тишина. Это и
    есть фикс: раньше это была главная причина спама каждые 30 минут."""
    command = Command()
    monkeypatch.setattr(command, "_get_last_notified_status", lambda: "warning")

    assert command._resolve_notify_decision("warning", True, False) is False


def test_status_change_triggers_notification(monkeypatch):
    """Смена статуса в любую сторону (включая возврат к healthy) —
    уведомляем."""
    command = Command()
    monkeypatch.setattr(command, "_get_last_notified_status", lambda: "warning")

    assert command._resolve_notify_decision("critical", True, False) is True
    assert command._resolve_notify_decision("healthy", True, False) is True


def test_get_and_set_last_notified_status_round_trip(monkeypatch):
    """Записанный статус читается обратно тем же ключом."""
    command = Command()
    fake_redis = _FakeRedis()
    _patch_redis(monkeypatch, fake_redis)

    assert command._get_last_notified_status() is None

    command._set_last_notified_status("critical")

    assert command._get_last_notified_status() == "critical"
    assert fake_redis.store[Command.HEALTH_STATUS_REDIS_KEY] == "critical"


def test_get_last_notified_status_fails_open_when_redis_unavailable(monkeypatch):
    """Redis недоступен → None, не исключение — handle() трактует это как
    «истории нет», а не как «всё сломано»."""
    command = Command()
    _patch_redis(monkeypatch, None)

    assert command._get_last_notified_status() is None


def test_set_last_notified_status_swallows_redis_errors(monkeypatch):
    """Запись не должна ронять health-check, если Redis моргнул."""
    command = Command()

    class _BrokenRedis:
        def set(self, key, value):
            raise ConnectionError("simulated redis outage")

    _patch_redis(monkeypatch, _BrokenRedis())

    command._set_last_notified_status("warning")  # не должно бросить исключение


def _run_health(
    monkeypatch,
    *,
    telegram=False,
    vk=False,
    success=True,
    status="critical",
    last_status=None
):
    output = StringIO()
    command = Command(stdout=output)
    calls, remembered = [], []
    monkeypatch.setattr(
        command,
        "_check_disk_usage",
        lambda: {"status": status, "message": "test disk result"},
    )
    monkeypatch.setattr(command, "_get_last_notified_status", lambda: last_status)
    monkeypatch.setattr(command, "_set_last_notified_status", remembered.append)

    def notify(overall_status, metrics, *, channels):
        calls.append((overall_status, channels))
        return success

    monkeypatch.setattr(
        health_module.TelegramErrorNotifier, "notify_system_health", notify
    )
    command.handle(
        check_all=False,
        check_db=False,
        check_disk=True,
        check_memory=False,
        check_web=False,
        check_telegram_proxy=False,
        check_backups=False,
        notify_telegram=telegram,
        notify_vk=vk,
        notify_always=False,
    )
    return calls, remembered, output.getvalue()


@pytest.mark.parametrize(
    "telegram,vk,channels",
    [
        (True, True, ("vk", "telegram")),
        (True, False, ("telegram",)),
        (False, True, ("vk",)),
    ],
)
def test_cli_calls_notifier_once_for_requested_channels(
    monkeypatch, caplog, telegram, vk, channels
):
    with caplog.at_level(logging.CRITICAL, logger=health_module.__name__):
        calls, remembered, output = _run_health(monkeypatch, telegram=telegram, vk=vk)
    assert calls == [("critical", channels)]
    assert remembered == ["critical"]
    assert "API подтвердил" in output
    assert len(caplog.records) == 1
    assert caplog.records[0].notification_handled is True


def test_cli_failed_or_suppressed_delivery_does_not_mark_status_notified(monkeypatch):
    calls, remembered, output = _run_health(monkeypatch, vk=True, success=False)
    assert calls == [("critical", ("vk",))]
    assert remembered == []
    assert "API подтвердил" not in output
    assert "Уведомление не отправлено" in output


def test_cli_without_notification_flags_only_logs_results(monkeypatch, caplog):
    calls, remembered, output = _run_health(monkeypatch)
    assert calls == []
    assert remembered == []
    assert "📤" not in output
    assert any(record.notification_handled for record in caplog.records)


def test_cli_unchanged_status_does_not_send_or_update_history(monkeypatch):
    calls, remembered, output = _run_health(
        monkeypatch, telegram=True, vk=True, last_status="critical"
    )
    assert calls == []
    assert remembered == []
    assert "отправка пропущена" in output
