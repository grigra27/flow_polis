import logging
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

import apps.core.telegram_handler as telegram_handler_module
import apps.core.notifications as notifications_module
import apps.core.tasks as tasks_module
from apps.core.telegram_handler import TelegramErrorNotifier, TelegramHandler


class _DedupRedis:
    def __init__(self, clock):
        self.clock = clock
        self.values = {}

    def set(self, key, token, nx=False, ex=None):
        cached = self.values.get(key)
        if cached is not None and cached[1] <= self.clock[0]:
            del self.values[key]
        if nx and key in self.values:
            return False
        self.values[key] = token, self.clock[0] + ex
        return True

    def eval(self, script, key_count, key, token):
        if self.values.get(key, (None,))[0] == token:
            del self.values[key]
            return 1
        return 0


@pytest.fixture(autouse=True)
def delivery(monkeypatch):
    """Only fakes: no Redis, Celery broker or external API calls."""
    clock = [0.0]
    client = _DedupRedis(clock)
    config = {
        "TELEGRAM_ENABLED": True,
        "TELEGRAM_BOT_TOKEN": "telegram-test-token",
        "TELEGRAM_CHAT_ID": "test-chat",
        "VK_ENABLED": True,
        "VK_COMMUNITY_TOKEN": "vk-test-token",
        "VK_USER_ID": "test-user",
    }
    monkeypatch.setattr(
        telegram_handler_module,
        "config",
        lambda key, default=None, cast=None: config.get(key, default),
    )
    monkeypatch.setattr(notifications_module, "_get_redis", lambda: client)
    monkeypatch.setattr(TelegramHandler, "_fallback_cache", {})
    monkeypatch.setattr(
        telegram_handler_module, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    limits = []

    def allow(scope, maximum):
        limits.append(scope)
        return True

    monkeypatch.setattr(telegram_handler_module, "check_rate_limit", allow)
    queued, sent = [], []

    def task(channel):
        return SimpleNamespace(delay=lambda message: queued.append((channel, message)))

    monkeypatch.setattr(tasks_module, "send_to_all_task", task("all"))
    monkeypatch.setattr(tasks_module, "send_vk_task", task("vk"))
    monkeypatch.setattr(tasks_module, "send_telegram_task", task("telegram"))

    def send(channel, message):
        sent.append((channel, message))
        return True

    monkeypatch.setattr(
        notifications_module, "send_vk", lambda message: send("vk", message)
    )
    monkeypatch.setattr(
        notifications_module, "send_telegram", lambda message: send("telegram", message)
    )
    return SimpleNamespace(
        config=config,
        clock=clock,
        client=client,
        limits=limits,
        queued=queued,
        sent=sent,
    )


def _build_record(exc_info=None):
    record = logging.LogRecord(
        name="django.request",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg="Internal Server Error: /admin/policies/policy/add/",
        args=(),
        exc_info=exc_info,
    )
    record.request = SimpleNamespace(
        user=SimpleNamespace(is_authenticated=True, username="tester", id=1),
        method="POST",
        get_full_path=lambda: "/admin/policies/policy/add/",
    )
    return record


def test_trim_with_middle_ellipsis_keeps_tail():
    handler = TelegramHandler()
    long_text = "BEGIN-" + ("X" * 500) + "-THE-END"

    trimmed = handler._trim_with_middle_ellipsis(
        long_text,
        max_length=80,
        marker="|...|",
        tail_ratio=0.8,
    )

    assert len(trimmed) <= 80
    assert trimmed.startswith("BEGIN-")
    assert trimmed.endswith("-THE-END")
    assert "|...|" in trimmed


def test_emit_delegates_to_celery_task_not_synchronous(monkeypatch):
    """
    После #8: emit() ставит task в Celery очередь, не вызывает send_to_all
    напрямую. Это снимает блокировку request handler'а на TG-таймауты.
    """
    handler = TelegramHandler()
    # Делаем handler "включённым" чтобы _should_send_message пропустил
    handler.enabled = True
    handler.bot_token = "x"
    handler.chat_id = "y"

    monkeypatch.setattr(
        telegram_handler_module, "check_rate_limit", lambda *a, **kw: True
    )

    delay_calls = []

    class FakeTask:
        @staticmethod
        def delay(text):
            delay_calls.append(text)

    # Мокаем импорт apps.core.tasks — он происходит лениво в _send_message_async
    import apps.core.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "send_to_all_task", FakeTask)

    # Проверяем, что исправная очередь не вызывает sync fallback.
    sync_calls = []
    monkeypatch.setattr(
        handler,
        "_send_message_sync",
        lambda text, channels: sync_calls.append(text),
    )

    record = _build_record()
    handler.emit(record)

    # Через Celery .delay() — да; синхронный send_to_all — нет.
    assert len(delay_calls) == 1
    assert sync_calls == []


def test_format_message_keeps_exception_tail_when_traceback_is_long(monkeypatch):
    handler = TelegramHandler()
    handler.traceback_limit = 220
    handler.telegram_message_limit = 4000

    fake_traceback = (
        "Traceback (most recent call last):\n"
        + ('  File "dummy.py", line 1, in fn\n    fn()\n' * 80)
        + "ValueError: final-exception-marker\n"
    )

    monkeypatch.setattr(
        telegram_handler_module.traceback,
        "format_exception",
        lambda *args, **kwargs: [fake_traceback],
    )

    exc_info = (ValueError, ValueError("boom"), None)
    record = _build_record(exc_info=exc_info)

    message = handler._format_message(record)

    assert "💥 Exception:" in message
    assert "ValueError: boom" in message
    assert "📋 Traceback:" in message
    assert "ValueError: final-exception-marker" in message
    assert "... (middle truncated) ..." in message


def test_custom_notifier_deduplicates_across_handler_instances_and_hosts(
    monkeypatch, delivery
):
    times = iter(
        [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ]
    )
    hosts = iter(["first-worker", "second-worker"])
    monkeypatch.setattr(telegram_handler_module, "get_moscow_time", lambda: next(times))
    monkeypatch.setattr(TelegramHandler, "_get_hostname", lambda self: next(hosts))

    assert TelegramErrorNotifier.notify_critical_error("failure", "same error") is True
    assert TelegramErrorNotifier.notify_critical_error("failure", "same error") is False
    assert len(delivery.queued) == 1
    assert delivery.limits == [TelegramHandler.ERROR_RATE_SCOPE]


def test_custom_notifier_and_log_errors_share_rate_budget(monkeypatch, delivery):
    used = []

    def one_alert(scope, maximum):
        used.append(scope)
        return len(used) == 1

    monkeypatch.setattr(telegram_handler_module, "check_rate_limit", one_alert)
    assert TelegramErrorNotifier.notify_critical_error("failure", "custom") is True
    TelegramHandler().emit(_build_record())
    assert len(delivery.queued) == 1
    assert used == [TelegramHandler.ERROR_RATE_SCOPE] * 2


def test_rate_limit_rejection_does_not_deduplicate_a_later_allowed_attempt(
    monkeypatch, delivery
):
    allowed = [False, True]
    monkeypatch.setattr(
        telegram_handler_module, "check_rate_limit", lambda *args: allowed.pop(0)
    )
    assert TelegramErrorNotifier.notify_critical_error("failure", "retry me") is False
    assert TelegramErrorNotifier.notify_critical_error("failure", "retry me") is True
    assert len(delivery.queued) == 1


def test_redis_outage_deduplicates_new_instances_until_ttl(monkeypatch, delivery):
    monkeypatch.setattr(notifications_module, "_get_redis", lambda: None)
    assert TelegramErrorNotifier.notify_critical_error("failure", "same error") is True
    assert TelegramErrorNotifier.notify_critical_error("failure", "same error") is False
    delivery.clock[0] += TelegramHandler.DEDUP_SECONDS + 1
    assert TelegramErrorNotifier.notify_critical_error("failure", "same error") is True
    assert len(delivery.queued) == 2


def test_healthy_status_does_not_consume_critical_error_budget(monkeypatch, delivery):
    used = set()

    def one_per_scope(scope, maximum):
        if scope in used:
            return False
        used.add(scope)
        return True

    monkeypatch.setattr(telegram_handler_module, "check_rate_limit", one_per_scope)
    assert TelegramErrorNotifier.notify_system_health("healthy", {"disk": "ok"}) is True
    assert (
        TelegramErrorNotifier.notify_critical_error("failure", "critical error") is True
    )
    assert used == {TelegramHandler.ERROR_RATE_SCOPE, "telegram_health_healthy"}
    assert len(delivery.sent) == 2
    assert len(delivery.queued) == 1


@pytest.mark.parametrize("source", ["logger", "custom"])
def test_vk_only_does_not_require_telegram_credentials(source, delivery):
    delivery.config.update(
        TELEGRAM_ENABLED=False, TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    )
    if source == "logger":
        TelegramHandler().emit(_build_record())
    else:
        assert TelegramErrorNotifier.notify_critical_error("failure", "custom") is True
    assert [channel for channel, _ in delivery.queued] == ["vk"]


def test_notifier_sanitizes_custom_payload_and_dedup_keys(delivery):
    assert (
        TelegramErrorNotifier.notify_critical_error(
            "failure",
            "password=private-test-value",
            {
                "token": "private-token-value",
                "url": "https://api.telegram.org/bottelegram-test-token/sendMessage",
            },
        )
        is True
    )
    message = delivery.queued[0][1]
    assert "private-test-value" not in message
    assert "private-token-value" not in message
    assert "telegram-test-token" not in message
    assert all(
        "private" not in key and "failure" not in key for key in delivery.client.values
    )


def test_log_exception_and_request_are_sanitized_before_dispatch(delivery):
    record = _build_record(
        (ValueError, ValueError("secret=private-exception-value"), None)
    )
    record.request.get_full_path = lambda: "/reset/?token=private-request-value"
    TelegramHandler().emit(record)
    message = delivery.queued[0][1]
    assert "private-exception-value" not in message
    assert "private-request-value" not in message


@pytest.mark.parametrize("source", ["error", "exception", "traceback", "request"])
def test_configured_token_is_masked_before_each_truncation(
    monkeypatch, delivery, source
):
    token = "BOUNDARY_PRIVATE_TOKEN_1234567890"  # pragma: allowlist secret
    delivery.config["TELEGRAM_BOT_TOKEN"] = token
    handler = TelegramHandler()
    handler.error_message_limit = 80
    handler.exception_message_limit = 120
    handler.traceback_limit = 140
    handler.telegram_message_limit = 4000
    record = _build_record()
    if source == "error":
        record.msg = "X" * 12 + token + "Y" * 180
    elif source == "exception":
        record.exc_info = ValueError, ValueError(token + "Y" * 180), None
    elif source == "traceback":
        record.exc_info = ValueError, ValueError("error"), None
        monkeypatch.setattr(
            telegram_handler_module.traceback,
            "format_exception",
            lambda *args: ["TRACE:" + token + "Y" * 180],
        )
    else:
        record.request.get_full_path = lambda: "/" + "x" * 80 + token
    handler.emit(record)
    message = delivery.queued[0][1]
    assert token not in message
    assert token[:12] not in message


def test_fingerprint_keeps_full_endpoint_and_exception_type(delivery):
    handler = TelegramHandler()
    first = _build_record((ValueError, ValueError("same"), None))
    second = _build_record((RuntimeError, RuntimeError("same"), None))
    handler.emit(first)
    handler.emit(second)
    third = _build_record((ValueError, ValueError("same"), None))
    third.request.get_full_path = lambda: "/" + "x" * 120 + "/different-endpoint/"
    handler.emit(third)
    assert len(delivery.queued) == 3


@pytest.mark.parametrize("name", TelegramHandler.INTERNAL_LOGGERS)
def test_delivery_logger_errors_remain_logged_without_reenqueue(name, delivery, caplog):
    logger = logging.getLogger(name)
    handler = TelegramHandler()
    logger.addHandler(handler)
    try:
        with caplog.at_level(logging.ERROR, logger=name):
            logger.error("delivery failed")
    finally:
        logger.removeHandler(handler)
    assert delivery.queued == []
    assert any(record.getMessage() == "delivery failed" for record in caplog.records)


def test_celery_delivery_task_failure_does_not_create_another_alert(delivery):
    record = _build_record()
    record.name = "celery.app.trace"
    record.data = {"name": "apps.core.tasks.send_telegram_task"}
    TelegramHandler().emit(record)
    assert delivery.queued == []


def test_explicit_health_notification_log_is_not_sent_twice(delivery):
    record = _build_record()
    record.notification_handled = True
    TelegramHandler().emit(record)
    assert delivery.queued == []


def test_sync_fallback_failure_is_false_sanitized_and_does_not_reenqueue(
    monkeypatch, delivery, capsys
):
    def broken_queue(message):
        raise RuntimeError("password=private-broker-value")

    def failed_vk(message):
        logging.getLogger("apps.core.vk_handler").error("API unavailable")
        raise RuntimeError("token=private-api-value")

    monkeypatch.setattr(
        tasks_module, "send_to_all_task", SimpleNamespace(delay=broken_queue)
    )
    monkeypatch.setattr(notifications_module, "send_vk", failed_vk)
    monkeypatch.setattr(notifications_module, "send_telegram", lambda message: False)
    logger = logging.getLogger("apps.core.vk_handler")
    handler = TelegramHandler()
    logger.addHandler(handler)
    try:
        assert (
            TelegramErrorNotifier.notify_critical_error("failure", "try again") is False
        )
    finally:
        logger.removeHandler(handler)
    output = capsys.readouterr().out
    assert "private-broker-value" not in output
    assert "private-api-value" not in output
    assert delivery.queued == []
    monkeypatch.setattr(notifications_module, "send_vk", lambda message: True)
    assert TelegramErrorNotifier.notify_critical_error("failure", "try again") is True


@pytest.mark.parametrize("channel", ["vk", "telegram"])
def test_health_sends_only_requested_channel_and_returns_api_result(
    channel, delivery, monkeypatch
):
    assert (
        TelegramErrorNotifier.notify_system_health("warning", channels=(channel,))
        is True
    )
    assert [name for name, _ in delivery.sent] == [channel]
    assert delivery.queued == []
    delivery.clock[0] += TelegramHandler.DEDUP_SECONDS + 1
    monkeypatch.setattr(notifications_module, "send_" + channel, lambda message: False)
    assert (
        TelegramErrorNotifier.notify_system_health("warning", channels=(channel,))
        is False
    )
