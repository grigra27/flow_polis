"""
Celery tasks для отправки нотификаций в Telegram + VK.

Зачем нужен async через Celery (а не sync вызов notifications.send_to_all):
  • TelegramHandler.emit() вызывается в request handler'ах. Telegram может
    зависнуть на timeout до 10 секунд из-за блокировок в РФ. Нельзя
    блокировать пользовательский запрос на это время.
  • VK тоже может быть медленным (хоть и быстрее).
  • Шторм ERROR'ов под Gunicorn без async = очередь request handler'ов.

Архитектура tasks (после #11.3):
  • send_to_all_task   — orchestrator: ставит send_vk_task и send_telegram_task
                         как отдельные подзадачи (VK first в очереди).
  • send_vk_task       — отправка только в VK. Без retry.
  • send_telegram_task — отправка только в TG. На HTTP 429 ретрит с задержкой
                         retry_after из ответа Telegram.

Разделение на подзадачи нужно чтобы при retry TG не повторялась отправка VK
(иначе при каждом TG-429 в VK уходил бы дубль).
"""
import logging

from celery import shared_task

from apps.core.notifications import (
    TelegramRateLimitError,
    send_telegram,
    send_to_all,
    send_vk,
)

logger = logging.getLogger(__name__)


@shared_task(name="apps.core.tasks.send_vk_task")
def send_vk_task(text: str) -> bool:
    """Отправляет сообщение в VK. Без retry (VK rate-limit не наблюдался)."""
    return send_vk(text)


@shared_task(
    name="apps.core.tasks.send_telegram_task",
    bind=True,
    max_retries=5,
)
def send_telegram_task(self, text: str) -> bool:
    """
    Отправляет сообщение в Telegram. На HTTP 429 ретрит с countdown,
    взятым из ответа Telegram (retry_after). До 5 повторов.

    Прочие ошибки (URLError, network unreachable, DNS) НЕ ретраятся —
    это типичные блокировки в РФ, повтор через секунду не поможет.
    Для них VK уже доставил алерт через send_vk_task.
    """
    try:
        return send_telegram(text, raise_on_rate_limit=True)
    except TelegramRateLimitError as exc:
        logger.warning(
            "Telegram 429, retry %s/%s after %ss",
            self.request.retries + 1,
            self.max_retries,
            exc.retry_after,
        )
        # countdown — точная задержка, без exponential backoff:
        # Telegram уже сказал сколько ждать.
        raise self.retry(exc=exc, countdown=exc.retry_after)


@shared_task(name="apps.core.tasks.send_to_all_task")
def send_to_all_task(text: str) -> dict:
    """
    Orchestrator: ставит подзадачи send_vk + send_telegram в Celery очередь.

    VK ставится в очередь ПЕРВЫМ (workers подберут в FIFO порядке) —
    резервный канал должен доставиться раньше Telegram, который может
    подвиснуть на 429-ретраях.

    Возвращает {"vk_task_id": ..., "telegram_task_id": ...} — caller'у
    обычно не нужно ждать результата.
    """
    vk_async = send_vk_task.delay(text)
    tg_async = send_telegram_task.delay(text)
    return {
        "vk_task_id": vk_async.id,
        "telegram_task_id": tg_async.id,
    }


# Backward-compat: старый sync-fallback (см. TelegramHandler._send_message_async)
# по-прежнему вызывает send_to_all из notifications. Если когда-то выпилим
# fallback — этот импорт можно убрать.
_ = send_to_all  # noqa: F401
