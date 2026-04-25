"""
Celery tasks для отправки нотификаций в Telegram + VK.

Зачем нужен async через Celery (а не sync вызов notifications.send_to_all):
  • TelegramHandler.emit() вызывается в request handler'ах. Telegram может
    зависнуть на timeout до 10 секунд из-за блокировок в РФ. Нельзя
    блокировать пользовательский запрос на это время.
  • VK тоже может быть медленным (хоть и быстрее).
  • Шторм ERROR'ов под Gunicorn без async = очередь request handler'ов.

Celery worker подхватывает задачу из очереди, отправляет, ретраит при сбое.
Если очередь/Redis недоступны — caller (TelegramHandler) делает fallback
на синхронную отправку (см. emit() docstring).
"""
import logging

from celery import shared_task

from apps.core.notifications import send_to_all

logger = logging.getLogger(__name__)


@shared_task(
    name="apps.core.tasks.send_to_all_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def send_to_all_task(self, text: str) -> dict:
    """
    Отправляет text в Telegram + VK (VK first — см. notifications.send_to_all).

    Retry: до 3 попыток с экспоненциальным backoff (jitter, max 5 мин)
    при любом исключении внутри send_to_all. Однако send_to_all сам
    ловит сетевые ошибки и возвращает {"vk": False, "telegram": False}
    без exception, поэтому retry в основном пригодится при катастрофах
    (например, redis-broker умер посреди обработки).
    """
    result = send_to_all(text)
    logger.info(
        "send_to_all_task completed: vk=%s telegram=%s",
        result.get("vk"),
        result.get("telegram"),
    )
    return result
