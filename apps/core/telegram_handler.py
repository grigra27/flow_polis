"""
Telegram Logging Handler for Django.

Этот модуль реализует только специфику logging-handler'а:
  • Rate-limit через Redis (общий для всех Gunicorn-воркеров)
  • Группировка одинаковых ошибок в Redis на 10 минут
  • Форматирование с emoji, timestamp, traceback, request info

Отправка делегируется в Celery-задачи выбранных каналов и не ждёт их API.
При недоступности очереди используется синхронная отправка в те же каналы.
"""
import logging
import hashlib
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from threading import Lock
from uuid import uuid4
from decouple import config
from apps.core.notifications import check_rate_limit
from apps.core.logging_filters import SensitiveDataFilter
from apps.core.notification_utils import trim_with_middle_ellipsis


def get_moscow_time():
    """Получает текущее время в московском часовом поясе"""
    moscow_tz = timezone(timedelta(hours=3))
    return datetime.now(moscow_tz)


class TelegramHandler(logging.Handler):
    """
    Logging handler для отправки критических ошибок в Telegram/VK.
    """

    ERROR_RATE_SCOPE = "telegram_handler"
    HEALTH_RATE_SCOPE_PREFIX = "telegram_health"
    DEDUP_KEY_PREFIX = "notification_dedup"
    DEDUP_SECONDS = 600
    FALLBACK_CACHE_MAX = 1024
    _fallback_cache = {}
    _fallback_lock = Lock()
    _RELEASE_CLAIM = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
    """
    INTERNAL_LOGGERS = (
        "apps.core.notifications",
        "apps.core.vk_handler",
        "apps.core.tasks",
        __name__,
    )

    def __init__(self, level=logging.ERROR):
        super().__init__(level)

        # Канал доступен только при enabled и полном наборе его настроек.
        self.bot_token = config("TELEGRAM_BOT_TOKEN", default="")
        self.chat_id = config("TELEGRAM_CHAT_ID", default="")
        self.enabled = config("TELEGRAM_ENABLED", default=False, cast=bool)
        self.vk_enabled = config("VK_ENABLED", default=False, cast=bool)
        self.vk_token = config("VK_COMMUNITY_TOKEN", default="")
        self.vk_user_id = config("VK_USER_ID", default="")
        self._sensitive_filter = SensitiveDataFilter()

        # Настройки rate limiting
        self.max_messages_per_hour = config(
            "TELEGRAM_ERROR_RATE_LIMIT", default=10, cast=int
        )
        self.error_message_limit = config(
            "TELEGRAM_ERROR_MESSAGE_LIMIT", default=500, cast=int
        )
        self.exception_message_limit = config(
            "TELEGRAM_EXCEPTION_MESSAGE_LIMIT", default=700, cast=int
        )
        self.traceback_limit = config(
            "TELEGRAM_TRACEBACK_LIMIT", default=2500, cast=int
        )
        # Telegram sendMessage hard limit is 4096 chars.
        self.telegram_message_limit = config(
            "TELEGRAM_MESSAGE_LIMIT", default=3900, cast=int
        )

    def emit(self, record):
        """Ставит ERROR+ в очередь; ошибки самой доставки не порождают алерты."""
        if (
            record.levelno < logging.ERROR
            or getattr(record, "notification_handled", False)
            or self._is_delivery_record(record)
        ):
            return
        try:
            self.notify_message(
                self._format_message(record), self._get_error_key(record)
            )
        except Exception as exc:
            # Не печатаем текст исключения: сетевые ошибки могут содержать ключи.
            print(f"TelegramHandler error: {type(exc).__name__}")

    @classmethod
    def _is_delivery_record(cls, record):
        if any(
            record.name == name or record.name.startswith(name + ".")
            for name in cls.INTERNAL_LOGGERS
        ):
            return True
        data = getattr(record, "data", {})
        task_name = getattr(record, "task_name", "")
        if isinstance(data, dict):
            task_name = data.get("name") or task_name
        return isinstance(task_name, str) and task_name.startswith("apps.core.tasks.")

    def _configured_channels(self, channels):
        requested = set(("vk", "telegram") if channels is None else channels)
        if requested - {"vk", "telegram"}:
            raise ValueError("Unknown notification channel")
        configured = {
            "vk": self.vk_enabled and self.vk_token and self.vk_user_id,
            "telegram": self.enabled and self.bot_token and self.chat_id,
        }
        return tuple(
            name
            for name in ("vk", "telegram")
            if name in requested and configured[name]
        )

    def _sanitize(self, message):
        message = str(message)
        for token in (self.bot_token, self.vk_token):
            if len(token) >= 8:
                message = message.replace(token, "***")
        record = logging.makeLogRecord({"msg": message, "args": ()})
        self._sensitive_filter.filter(record)
        return record.getMessage()

    def _claim_notification(self, scope, identity, channels):
        from apps.core.notifications import _get_redis

        fingerprint = hashlib.sha256(
            self._sanitize(identity).encode("utf-8")
        ).hexdigest()
        key = f"{self.DEDUP_KEY_PREFIX}:{scope}:{','.join(channels)}:{fingerprint}"
        token = uuid4().hex
        client = _get_redis()
        if client is not None:
            try:
                if not client.set(key, token, nx=True, ex=self.DEDUP_SECONDS):
                    return None
                return client, key, token
            except Exception:
                pass

        # Redis outage: new Handler instances still share a bounded TTL cache.
        now = time.monotonic()
        with self._fallback_lock:
            expired = [
                key
                for key, (deadline, _) in self._fallback_cache.items()
                if deadline <= now
            ]
            for expired_key in expired:
                del self._fallback_cache[expired_key]
            if key in self._fallback_cache:
                return None
            if len(self._fallback_cache) >= self.FALLBACK_CACHE_MAX:
                del self._fallback_cache[next(iter(self._fallback_cache))]
            self._fallback_cache[key] = now + self.DEDUP_SECONDS, token
        return None, key, token

    def _release_notification(self, claim):
        client, key, token = claim
        if client is not None:
            try:
                client.eval(self._RELEASE_CLAIM, 1, key, token)
            except Exception:
                pass
        else:
            with self._fallback_lock:
                cached = self._fallback_cache.get(key)
                if cached is not None and cached[1] == token:
                    del self._fallback_cache[key]

    def notify_message(
        self, message, identity, *, channels=None, scope=None, asynchronous=True
    ):
        """True: очередь приняла сообщение или хотя бы один API подтвердил отправку."""
        channels = self._configured_channels(channels)
        if not channels:
            return False
        scope = scope or self.ERROR_RATE_SCOPE
        message = self._trim_with_middle_ellipsis(
            self._sanitize(message), self.telegram_message_limit
        )
        claim = self._claim_notification(scope, identity, channels)
        if claim is None:
            return False
        accepted = False
        try:
            if not check_rate_limit(scope, self.max_messages_per_hour):
                return False
            if asynchronous:
                accepted = self._send_message_async(message, channels)
            else:
                accepted = self._send_message_sync(message, channels)
            return accepted
        finally:
            if not accepted:
                self._release_notification(claim)

    def _get_error_key(self, record):
        """
        Создает ключ для группировки одинаковых ошибок
        """
        key_parts = [record.name, record.module, record.getMessage()]
        if record.exc_info and record.exc_info[0]:
            exception_type, exception, _ = record.exc_info
            key_parts.extend(
                [
                    f"{exception_type.__module__}.{exception_type.__qualname__}",
                    str(exception),
                ]
            )
        request = getattr(record, "request", None)
        if request is not None:
            key_parts.extend([getattr(request, "method", ""), request.get_full_path()])
        return json.dumps(key_parts, ensure_ascii=False)

    def _format_message(self, record):
        """
        Форматирует сообщение для Telegram
        """
        # Конвертируем время записи в московское время
        moscow_tz = timezone(timedelta(hours=3))
        record_time = datetime.fromtimestamp(record.created, tz=moscow_tz)
        timestamp = record_time.strftime("%Y-%m-%d %H:%M:%S MSK")

        # Базовая информация
        message_parts = [
            "🚨 Critical Error Detected",
            "",
            f"🕐 Time: {timestamp}",
            f"📊 Level: {record.levelname}",
            f"📁 Module: {record.module or 'unknown'}",
            f"🖥 Server: {self._get_hostname()}",
        ]

        # Добавляем информацию о пользователе если есть
        if hasattr(record, "request") and record.request:
            request = record.request
            user_info = "Anonymous"
            if hasattr(request, "user") and request.user.is_authenticated:
                user_info = f"{request.user.username} (ID: {request.user.id})"

            message_parts.extend(
                [
                    f"👤 User: {user_info}",
                    f"🌐 URL: {self._sanitize(request.get_full_path())[:100]}",
                    f"📱 Method: {request.method}",
                ]
            )

        # Добавляем сообщение об ошибке
        error_message = record.getMessage()
        error_message = self._trim_with_middle_ellipsis(
            error_message,
            self.error_message_limit,
            marker=" ... (truncated) ... ",
            tail_ratio=0.5,
        )

        message_parts.extend(
            [
                "",
                f"❗ Error:",
                f"{error_message}",
            ]
        )

        # Добавляем тип и текст исключения отдельно, чтобы было видно "что именно упало",
        # даже если traceback пришлось сократить.
        if record.exc_info and record.exc_info[0]:
            exc_type = record.exc_info[0].__name__
            exc_value = str(record.exc_info[1]) if record.exc_info[1] else ""
            exc_line = f"{exc_type}: {exc_value}".strip()
            exc_line = self._trim_with_middle_ellipsis(
                exc_line,
                self.exception_message_limit,
                marker=" ... (truncated) ... ",
                tail_ratio=0.7,
            )
            message_parts.extend(
                [
                    "",
                    "💥 Exception:",
                    exc_line,
                ]
            )

        # Добавляем traceback если есть
        if record.exc_info:
            tb_lines = traceback.format_exception(*record.exc_info)
            tb_text = "".join(tb_lines)

            # Ограничиваем размер traceback, сохраняя и начало, и конец.
            # Конец traceback особенно важен, там обычно тип и текст исключения.
            tb_text = self._trim_with_middle_ellipsis(
                tb_text,
                self.traceback_limit,
                marker="\n... (middle truncated) ...\n",
                tail_ratio=0.8,
            )

            message_parts.extend(
                [
                    "",
                    f"📋 Traceback:",
                    f"{tb_text}",
                ]
            )

        message = self._sanitize("\n".join(message_parts))
        if len(message) > self.telegram_message_limit:
            message = self._trim_with_middle_ellipsis(
                message,
                self.telegram_message_limit,
                marker="\n... (message truncated) ...\n",
                tail_ratio=0.8,
            )

        return message

    def _trim_with_middle_ellipsis(
        self, text, max_length, marker=" ... ", tail_ratio=0.7
    ):
        """Скрывает секрет целиком до обрезки, сохраняя полезный хвост ошибки."""
        safe_text = None if text is None else self._sanitize(text)
        return trim_with_middle_ellipsis(safe_text, max_length, marker, tail_ratio)

    def _escape_html(self, text):
        """
        Экранирует HTML символы для Telegram
        """
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _get_hostname(self):
        """
        Получает имя хоста
        """
        try:
            import socket

            return socket.gethostname()
        except Exception:
            return "unknown"

    def _send_message_async(self, message, channels):
        """
        True означает принятую задачу, а не подтверждение доставки API.
        При отказе очереди пробует выбранные каналы синхронно.
        """
        try:
            from apps.core.tasks import (
                send_to_all_task,
                send_telegram_task,
                send_vk_task,
            )

            task = (
                send_to_all_task
                if len(channels) == 2
                else send_vk_task
                if channels == ("vk",)
                else send_telegram_task
            )
            task.delay(message)
            return True
        except Exception as exc:
            print(
                f"TelegramHandler: очередь недоступна, sync fallback ({type(exc).__name__})"
            )
            return self._send_message_sync(message, channels)

    def _send_message_sync(self, message, channels):
        from apps.core.notifications import send_telegram, send_vk

        sent = False
        for channel in channels:
            try:
                delivered = (
                    send_vk(message) if channel == "vk" else send_telegram(message)
                )
                sent = bool(delivered) or sent
            except Exception as exc:
                print(f"TelegramHandler: ошибка {channel} ({type(exc).__name__})")
        return sent


class TelegramErrorNotifier:
    """
    Утилитный класс для отправки кастомных уведомлений об ошибках
    """

    @staticmethod
    def notify_critical_error(title, message, details=None):
        """
        True: уведомление принято очередью или отправлено sync fallback.
        """
        handler = TelegramHandler()

        timestamp = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S MSK")

        message_parts = [
            f"🚨 {title}",
            "",
            f"🕐 Time: {timestamp}",
            f"🖥 Server: {handler._get_hostname()}",
            "",
            f"📝 Message:",
            f"{message}",
        ]

        if details:
            message_parts.extend(
                [
                    "",
                    f"📋 Details:",
                    f"{str(details)}",
                ]
            )

        formatted_message = "\n".join(message_parts)

        identity = json.dumps(
            ["custom_error", title, message, details], sort_keys=True, default=str
        )
        return handler.notify_message(formatted_message, identity)

    @staticmethod
    def notify_system_health(status, metrics=None, *, channels=None):
        """
        Синхронно уведомляет выбранные каналы; True — хотя бы один API success.
        """
        handler = TelegramHandler()

        timestamp = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S MSK")
        status_emoji = (
            "✅" if status == "healthy" else "⚠️" if status == "warning" else "❌"
        )

        message_parts = [
            f"{status_emoji} System Health Check",
            "",
            f"🕐 Time: {timestamp}",
            f"📊 Status: {status.upper()}",
            f"🖥 Server: {handler._get_hostname()}",
        ]

        if metrics:
            message_parts.append("")
            message_parts.append("📈 Metrics:")
            for key, value in metrics.items():
                message_parts.append(f"• {key}: {value}")

        formatted_message = "\n".join(message_parts)

        identity = json.dumps(
            ["system_health", status, metrics], sort_keys=True, default=str
        )
        scope = (
            handler.ERROR_RATE_SCOPE
            if status == "critical"
            else f"{handler.HEALTH_RATE_SCOPE_PREFIX}_{status}"
        )
        return handler.notify_message(
            formatted_message,
            identity,
            channels=channels,
            scope=scope,
            asynchronous=False,
        )
