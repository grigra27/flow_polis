import logging
from types import SimpleNamespace

import apps.core.telegram_handler as telegram_handler_module
from apps.core.telegram_handler import TelegramHandler


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
