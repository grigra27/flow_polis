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
import os
import random
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import requests
from decouple import config

# Reuse существующая VK-отправка — она содержит все нюансы (random_id,
# обработка кода ошибок VK API, проверка enabled/token/user_id).
from apps.core.vk_handler import VK_API_VERSION, send_vk_message

logger = logging.getLogger(__name__)


class TelegramRateLimitError(Exception):
    """
    HTTP 429 от Telegram API. retry_after — рекомендованная задержка
    в секундах перед следующей попыткой (из JSON body или Retry-After
    header ответа). Используется в Celery task для self.retry(countdown=...).
    """

    def __init__(self, retry_after: int, raw: str = ""):
        self.retry_after = retry_after
        self.raw = raw
        super().__init__(f"Telegram rate-limited, retry after {retry_after}s")


def _parse_retry_after(exc, body: str) -> int:
    """
    Извлекает retry_after из ответа Telegram на 429.

    Telegram возвращает либо в JSON body:
      {"ok": false, "error_code": 429, "parameters": {"retry_after": 30}}
    либо в HTTP заголовке Retry-After.

    Default: 60 секунд если ничего не нашли.
    """
    # 1) JSON body
    try:
        data = json.loads(body) if body else {}
        params = data.get("parameters") or {}
        ra = params.get("retry_after")
        if isinstance(ra, int) and ra > 0:
            return ra
    except (ValueError, TypeError):
        pass
    # 2) HTTP header
    try:
        header_val = exc.headers.get("Retry-After") if exc.headers else None
        if header_val:
            return max(1, int(header_val))
    except (ValueError, AttributeError, TypeError):
        pass
    # 3) Default — Telegram обычно просит 1-60 сек, берём верхнюю границу
    return 60


# Lazy-init redis-клиент. Создаётся при первом обращении.
# Если Redis недоступен — rate-limit fail-open (пропускаем),
# лучше дубль чем потеря алерта.
_redis_client = None


def _get_redis():
    """Возвращает redis-клиент или None если подключиться нельзя."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis

        url = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
        _redis_client = redis.Redis.from_url(url, socket_timeout=2)
        # Lazy ping — проверим что redis отвечает. Если нет — None.
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning("Redis недоступен для rate-limit, fail-open: %s", e)
        _redis_client = None
        return None


def check_rate_limit(scope: str, max_per_hour: int = 10) -> bool:
    """
    Атомарный sliding-hour rate limit через Redis INCR.

    scope — логический неймспейс ("telegram_handler", "system_health", ...)
    max_per_hour — лимит для этого scope в текущем часе.

    Возвращает True если можно отправить, False если упёрлись в лимит.
    Common для всех Gunicorn-воркеров: один счётчик, не N×limit.

    Если Redis недоступен — возвращает True (fail-open). Лучше дубль
    в Telegram чем потерять алерт из-за инфраструктурной проблемы.
    """
    r = _get_redis()
    if r is None:
        return True
    try:
        hour = datetime.now().strftime("%Y%m%d%H")
        key = f"rate_limit:{scope}:{hour}"
        count = r.incr(key)
        if count == 1:
            # Первый incr в этом часе — ставим TTL чуть больше часа на случай
            # если кто-то проверит сразу после смены часа.
            r.expire(key, 3700)
        return count <= max_per_hour
    except Exception as e:
        logger.warning("Redis rate-limit INCR failed, fail-open: %s", e)
        return True


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


def send_telegram(text: str, raise_on_rate_limit: bool = False) -> bool:
    """
    Отправляет одно сообщение в Telegram. Возвращает True/False.

    Конфигурация:
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — обязательные
        TELEGRAM_ENABLED — true/false (по умолчанию false)

    При TELEGRAM_ENABLED=false или отсутствии токена/чата возвращает False
    без попытки отправки. При сетевой ошибке логирует и возвращает False
    (исключение НЕ пробрасывается — caller'у достаточно знать что не дошло).

    raise_on_rate_limit:
        Если True — на HTTP 429 поднимает TelegramRateLimitError(retry_after).
        Используется Celery task'ом send_telegram_task для self.retry с точной
        задержкой по указанию Telegram. Default False — для совместимости
        с прямыми вызовами (daily_digest, ручные тесты), которым retry не нужен.

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
        try:
            error_body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        except Exception:
            error_body = ""
        # 429 = Telegram rate-limit. Если caller хочет retry — поднимаем
        # exception с точной задержкой. Иначе логируем как обычную ошибку.
        if e.code == 429 and raise_on_rate_limit:
            retry_after = _parse_retry_after(e, error_body)
            logger.warning(
                "Telegram 429, will retry after %ss: %s", retry_after, error_body
            )
            raise TelegramRateLimitError(retry_after, raw=error_body)
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


# Таймаут для VK file upload — 60 секунд (multipart upload медленнее обычных API-вызовов)
VK_FILE_TIMEOUT = 60
VK_API_BASE = "https://api.vk.com/method"


def send_vk_file(file_path: str, caption: str = "") -> bool:
    """
    Отправляет файл в VK как документ конкретному пользователю.

    Конфигурация (та же что и для send_vk_message):
        VK_COMMUNITY_TOKEN, VK_USER_ID, VK_ENABLED

    4-шаговый процесс по VK API (портирован из bash send_vk_file
    в scripts/telegram-notify.sh):
      1) docs.getMessagesUploadServer → upload_url
      2) POST upload_url с multipart файлом → file token
      3) docs.save с file token → owner_id, doc_id
      4) messages.send с attachment=doc{owner_id}_{id} + caption

    Возвращает True/False. На любой ошибке (network, VK API error, файл
    не найден) — логирует и возвращает False, не падает.
    """
    token = config("VK_COMMUNITY_TOKEN", default="")
    user_id = config("VK_USER_ID", default="")
    enabled = config("VK_ENABLED", default=False, cast=bool)

    if not enabled:
        logger.debug("VK отправка отключена (VK_ENABLED=false)")
        return False
    if not token or not user_id:
        logger.error("VK не настроен: отсутствует VK_COMMUNITY_TOKEN или VK_USER_ID")
        return False
    if not os.path.isfile(file_path):
        logger.error("VK file upload: файл не найден: %s", file_path)
        return False

    base_params = {"access_token": token, "v": VK_API_VERSION}

    try:
        # Шаг 1: получить upload URL
        r = requests.post(
            f"{VK_API_BASE}/docs.getMessagesUploadServer",
            data={**base_params, "peer_id": user_id, "type": "doc"},
            timeout=VK_FILE_TIMEOUT,
        )
        data = r.json()
        if "error" in data:
            logger.error("VK docs.getMessagesUploadServer: %s", data["error"])
            return False
        upload_url = (data.get("response") or {}).get("upload_url")
        if not upload_url:
            logger.error("VK upload URL не получен: %s", data)
            return False

        # Шаг 2: загрузить файл
        with open(file_path, "rb") as f:
            r = requests.post(upload_url, files={"file": f}, timeout=VK_FILE_TIMEOUT)
        data = r.json()
        if "error" in data:
            logger.error("VK upload error: %s", data["error"])
            return False
        file_token = data.get("file")
        if not file_token:
            logger.error("VK file token не получен: %s", data)
            return False

        # Шаг 3: сохранить как VK-документ
        title = os.path.basename(file_path)
        r = requests.post(
            f"{VK_API_BASE}/docs.save",
            data={**base_params, "file": file_token, "title": title},
            timeout=VK_FILE_TIMEOUT,
        )
        data = r.json()
        if "error" in data:
            logger.error("VK docs.save: %s", data["error"])
            return False

        # docs.save возвращает либо response.doc.{owner_id, id},
        # либо response[0].{owner_id, id} — поддерживаем оба формата
        # (как в bash-версии send_vk_file).
        response = data.get("response")
        owner_id = doc_id = None
        if isinstance(response, dict):
            doc = response.get("doc") or {}
            owner_id = doc.get("owner_id")
            doc_id = doc.get("id")
        elif isinstance(response, list) and response:
            owner_id = response[0].get("owner_id")
            doc_id = response[0].get("id")
        if not owner_id or not doc_id:
            logger.error("VK docs.save: doc identifiers не найдены: %s", data)
            return False

        attachment = f"doc{owner_id}_{doc_id}"

        # Шаг 4: отправить документ как сообщение
        random_id = random.randint(1, 2**31 - 1)
        r = requests.post(
            f"{VK_API_BASE}/messages.send",
            data={
                **base_params,
                "user_id": user_id,
                "message": caption or "",
                "attachment": attachment,
                "random_id": random_id,
            },
            timeout=VK_FILE_TIMEOUT,
        )
        data = r.json()
        if "error" in data:
            logger.error("VK messages.send (with attachment): %s", data["error"])
            return False

        logger.info("VK file sent: %s as %s", file_path, attachment)
        return True

    except requests.RequestException as e:
        logger.error("VK file upload network error: %s", e)
        return False
    except Exception as e:
        logger.error("VK file upload unexpected error: %s", e, exc_info=True)
        return False
