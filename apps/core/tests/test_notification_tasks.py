"""Execute notification tasks without a broker to verify channel-local retry."""

from types import SimpleNamespace

import pytest
from celery.exceptions import Retry

from apps.core import tasks
from apps.core.notifications import TelegramRateLimitError


def _run_as_eager_worker(task, text, retries):
    task.push_request(
        id="notification-test",
        args=(text,),
        kwargs={},
        retries=retries,
        called_directly=False,
        is_eager=True,
    )
    try:
        return task.run(text)
    finally:
        task.pop_request()


def test_telegram_429_retries_only_telegram_after_single_vk_delivery(monkeypatch):
    queued = []
    deliveries = []

    def enqueue(task):
        def delay(text):
            queued.append((task, text))
            return SimpleNamespace(id=task.name)

        return delay

    def send_vk(text):
        deliveries.append("vk")
        return True

    def send_telegram(text, raise_on_rate_limit=False):
        assert raise_on_rate_limit is True
        deliveries.append("telegram")
        if deliveries.count("telegram") <= 2:
            raise TelegramRateLimitError(42)
        return True

    monkeypatch.setattr(tasks.send_vk_task, "delay", enqueue(tasks.send_vk_task))
    monkeypatch.setattr(
        tasks.send_telegram_task, "delay", enqueue(tasks.send_telegram_task)
    )
    monkeypatch.setattr(tasks, "send_vk", send_vk)
    monkeypatch.setattr(tasks, "send_telegram", send_telegram)

    result = tasks.send_to_all_task.run("diagnostic")

    assert [task.name for task, text in queued] == [
        tasks.send_vk_task.name,
        tasks.send_telegram_task.name,
    ]
    assert result == {
        "vk_task_id": tasks.send_vk_task.name,
        "telegram_task_id": tasks.send_telegram_task.name,
    }
    assert queued[0][0].run(queued[0][1]) is True
    telegram_task, text = queued[1]
    for attempt in range(2):
        with pytest.raises(Retry) as caught:
            _run_as_eager_worker(telegram_task, text, retries=attempt)
        assert caught.value.when == 42
        assert caught.value.sig.task == tasks.send_telegram_task.name
    assert _run_as_eager_worker(telegram_task, text, retries=2) is True
    assert deliveries == ["vk", "telegram", "telegram", "telegram"]


def test_telegram_rate_limit_retry_remains_bounded(monkeypatch):
    def rate_limited(*args, **kwargs):
        raise TelegramRateLimitError(17)

    monkeypatch.setattr(tasks, "send_telegram", rate_limited)

    with pytest.raises(TelegramRateLimitError):
        _run_as_eager_worker(
            tasks.send_telegram_task,
            "diagnostic",
            retries=tasks.send_telegram_task.max_retries,
        )
