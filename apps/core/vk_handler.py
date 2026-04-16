"""
Отправка сообщений через VK Communities API.
Используется для рассылки дайджеста конкретному пользователю от лица сообщества.
"""
import json
import logging
import random
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from decouple import config

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method/messages.send"
VK_API_VERSION = "5.199"
# Лимит VK на длину одного сообщения
VK_MAX_MESSAGE_LENGTH = 4096


def send_vk_message(text: str) -> bool:
    """
    Отправляет одно сообщение пользователю через VK Communities API.

    Возвращает True при успехе, False при любой ошибке.
    Конфигурация берётся из переменных окружения:
        VK_COMMUNITY_TOKEN  — ключ доступа сообщества
        VK_USER_ID          — id получателя
        VK_ENABLED          — true/false
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

    if len(text) > VK_MAX_MESSAGE_LENGTH:
        logger.warning(
            "Сообщение для VK превышает лимит (%d символов), будет обрезано",
            len(text),
        )
        text = text[:VK_MAX_MESSAGE_LENGTH]

    # random_id — обязательный параметр VK API, защищает от повторной отправки
    # при retry. Уникален в рамках одного запуска.
    random_id = random.randint(1, 2**31 - 1)

    data = {
        "user_id": user_id,
        "message": text,
        "random_id": random_id,
        "access_token": token,
        "v": VK_API_VERSION,
    }

    encoded = urlencode(data).encode("utf-8")
    request = Request(
        VK_API_URL,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            result = json.loads(body)

            if "error" in result:
                err = result["error"]
                logger.error(
                    "VK API вернул ошибку %s: %s",
                    err.get("error_code"),
                    err.get("error_msg"),
                )
                return False

            logger.debug(
                "VK: сообщение отправлено, message_id=%s", result.get("response")
            )
            return True

    except HTTPError as e:
        error_body = ""
        if hasattr(e, "read"):
            error_body = e.read().decode("utf-8")
        logger.error("VK HTTP %s: %s | %s", e.code, e.reason, error_body)
        return False
    except Exception as e:
        logger.error("Ошибка при отправке VK-сообщения: %s", e)
        return False
