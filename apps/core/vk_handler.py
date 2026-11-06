"""
Отправка сообщений через VK Communities API.
Используется для рассылки дайджеста конкретному пользователю от лица сообщества.
"""
import json
import logging
import secrets
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from decouple import config

from apps.core.notification_utils import trim_with_middle_ellipsis

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method/messages.send"
VK_API_VERSION = "5.199"
# Existing conservative budget; the VK API 5.199 schema allows up to 9000.
VK_MAX_MESSAGE_LENGTH = 4096

# Атрибуция источника (2026-09-24): в этот же VK-диалог шлют сообщения и
# другие проекты, поэтому без явной пометки непонятно, откуда пришло
# конкретное сообщение. Проставляется только в VK — Telegram (см.
# apps.core.notifications.send_telegram) для этого получателя выделен
# под данный проект отдельно и в атрибуции не нуждается.
VK_ATTRIBUTION_PREFIX = "🏢 polis.insflow"


def new_vk_random_id() -> int:
    """Nonzero int32 from OS entropy, independent of process PRNG state.

    VK uses random_id for duplicate suppression. Random draws still have a
    collision probability; this is not a persistent uniqueness guarantee.
    """
    return secrets.randbelow(2**31 - 1) + 1


def format_vk_message(text: str, separator: str = "\n\n") -> str:
    """Keep attribution and the diagnostic tail within the existing budget."""
    text = "" if text is None else str(text)
    if not text:
        return VK_ATTRIBUTION_PREFIX
    prefix = VK_ATTRIBUTION_PREFIX + separator
    if len(prefix) + len(text) > VK_MAX_MESSAGE_LENGTH:
        logger.warning(
            "Сообщение для VK превышает лимит (%d символов), будет обрезано",
            len(prefix) + len(text),
        )
    return prefix + trim_with_middle_ellipsis(text, VK_MAX_MESSAGE_LENGTH - len(prefix))


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

    text = format_vk_message(text)
    random_id = new_vk_random_id()

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
