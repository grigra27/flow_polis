"""
Единая точка отправки нотификаций в Telegram и VK.

Создан для устранения дублирования: раньше HTTP-запросы к Telegram API
были разбросаны по trois файлам (telegram_handler.py, daily_digest.py,
а также vk_handler.py для VK). Теперь вся низкоуровневая работа здесь.

Принципы (см. docs/NOTIFICATIONS_PIPELINE.md, секция «Главный бизнес-принцип»):
  • VK — резервный 100%-канал. Сервер в РФ, Telegram блокируется.
  • VK отправляется ПЕРВЫМ — не задерживаемся на TG-таймаутах.
  • Любой новый код, шлющий в TG, обязан использовать send_to_all().
"""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from decouple import config

# Reuse существующая VK-отправка — она содержит все нюансы (random_id,
# обработка кода ошибок VK API, проверка enabled/token/user_id).
from apps.core.vk_handler import send_vk_message

logger = logging.getLogger(__name__)

# Hard limit Telegram sendMessage — 4096 символов. Берём с запасом.
TELEGRAM_MESSAGE_LIMIT = 3900
# Hard limit VK messages.send — 4096 символов.
VK_MESSAGE_LIMIT = 4096
# Таймаут для одного HTTP-запроса к Telegram API (секунды).
TELEGRAM_TIMEOUT = 10


def trim_with_middle_ellipsis(
    text: str,
    max_length: int,
    marker: str = " ... (truncated) ... ",
    tail_ratio: float = 0.7,
) -> str:
    """
    Обрезает длинный текст, сохраняя начало и конец.
    Полезно для traceback'ов — конец содержит тип/сообщение исключения.

    tail_ratio=0.7 значит: 30% места под начало, 70% под конец.
    """
    if text is None:
        return ""
    text = str(text)
    if max_length is None or max_length <= 0 or len(text) <= max_length:
        return text
    marker = str(marker)
    if max_length <= len(marker) + 10:
        return text[-max_length:]
    available = max_length - len(marker)
    tail_len = int(available * tail_ratio)
    head_len = available - tail_len
    if head_len < 1:
        head_len = 1
        tail_len = available - head_len
    if tail_len < 1:
        tail_len = 1
        head_len = available - tail_len
    return text[:head_len] + marker + text[-tail_len:]


def send_telegram(text: str) -> bool:
    """
    Отправляет одно сообщение в Telegram. Возвращает True/False.

    Конфигурация:
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — обязательные
        TELEGRAM_ENABLED — true/false (по умолчанию false)

    При TELEGRAM_ENABLED=false или отсутствии токена/чата возвращает False
    без попытки отправки. При сетевой ошибке логирует и возвращает False
    (исключение НЕ пробрасывается — caller'у достаточно знать что не дошло).

    Длина обрезается до TELEGRAM_MESSAGE_LIMIT с сохранением начала и конца
    (важно для traceback'ов).
    """
    bot_token = config("TELEGRAM_BOT_TOKEN", default="")
    chat_id = config("TELEGRAM_CHAT_ID", default="")
    enabled = config("TELEGRAM_ENABLED", default=False, cast=bool)

    if not enabled:
        logger.debug("Telegram отправка отключена (TELEGRAM_ENABLED=false)")
        return False
    if not bot_token or not chat_id:
        logger.error(
            "Telegram не настроен: отсутствует TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID"
        )
        return False

    text = trim_with_middle_ellipsis(text, TELEGRAM_MESSAGE_LIMIT)

    data = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    encoded = urlencode(data).encode("utf-8")
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    request = Request(
        api_url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urlopen(request, timeout=TELEGRAM_TIMEOUT) as response:
            body = response.read().decode("utf-8")
            result = json.loads(body)
            if result.get("ok"):
                logger.debug("Telegram: сообщение отправлено")
                return True
            logger.error("Telegram API вернул ошибку: %s", result)
            return False
    except HTTPError as e:
        # Отдельный handling 429: уважительное retry — задача #11.3
        try:
            error_body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        except Exception:
            error_body = ""
        logger.error("Telegram HTTP %s: %s | %s", e.code, e.reason, error_body)
        return False
    except URLError as e:
        # Сюда падают timeouts, DNS-ошибки, network unreachable — норма для
        # сервера в РФ при блокировке Telegram. VK должен компенсировать.
        logger.error("Telegram network error: %s", e)
        return False
    except Exception as e:
        logger.error("Telegram unexpected error: %s", e)
        return False


def send_vk(text: str) -> bool:
    """
    Отправляет сообщение в VK. Возвращает True/False.
    Тонкая обёртка над send_vk_message — оставлена ради единообразия
    с send_telegram (можно вызывать notifications.send_vk вместо
    импорта vk_handler напрямую).
    """
    return send_vk_message(text)


def send_to_all(text: str) -> dict:
    """
    Отправляет сообщение во ВСЕ настроенные каналы (VK + Telegram).

    VK — ПЕРВЫМ. Это критично:
      • VK = 100%-резервный канал, должен быть быстрым и надёжным.
      • Telegram может зависнуть на timeout до 10 секунд из-за блокировок.

    Каждый канал отправляется независимо: если один упал — другой всё
    равно попробует. Возвращает {"vk": bool, "telegram": bool} —
    минимум один True означает что сообщение доставлено хотя бы куда-то.
    """
    vk_ok = send_vk(text)
    tg_ok = send_telegram(text)
    return {"vk": vk_ok, "telegram": tg_ok}
