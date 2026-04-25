"""
Telegram Logging Handler for Django.

Этот модуль реализует только специфику logging-handler'а:
  • Rate-limit (10 сообщений в час, in-memory)
  • Группировка одинаковых ошибок (раз в 10 мин)
  • Форматирование с emoji, timestamp, traceback, request info

Сама отправка делегируется в apps.core.notifications.send_to_all,
которая знает про VK-first, обрезку, retry — см. notifications.py.
"""
import logging
import traceback
from datetime import datetime, timezone, timedelta
from decouple import config
from apps.core.notifications import send_to_all


def get_moscow_time():
    """Получает текущее время в московском часовом поясе"""
    moscow_tz = timezone(timedelta(hours=3))
    return datetime.now(moscow_tz)


class TelegramHandler(logging.Handler):
    """
    Кастомный logging handler для отправки критических ошибок в Telegram
    """

    def __init__(self, level=logging.ERROR):
        super().__init__(level)

        # Загружаем настройки Telegram из переменных окружения
        self.bot_token = config("TELEGRAM_BOT_TOKEN", default="")
        self.chat_id = config("TELEGRAM_CHAT_ID", default="")
        self.enabled = config("TELEGRAM_ENABLED", default=False, cast=bool)

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
        self.message_cache = {}  # Кэш для группировки одинаковых ошибок
        self.sent_messages = []  # История отправленных сообщений для rate limiting

        # URL для Telegram API
        if self.bot_token:
            self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        else:
            self.api_url = None

    def emit(self, record):
        """
        Отправляет лог-запись в Telegram + VK.

        Раньше отправка шла в Thread(daemon=True) — но в management
        command'ах daemon thread убивался при выходе процесса до того,
        как успевала уйти HTTP-запись. Сообщения терялись.

        Теперь синхронно: блокирует логгер до 10s × (TG + VK).
        Это приемлемо: rate-limit не даст спамить, а критичные ошибки
        важнее доли секунды задержки в request handler'е.
        """
        if not self._should_send_message(record):
            return

        try:
            message = self._format_message(record)
            self._send_message_async(message)
        except Exception as e:
            # Не должны падать если не можем отправить в Telegram
            print(f"TelegramHandler error: {e}")

    def _should_send_message(self, record):
        """
        Проверяет нужно ли отправлять сообщение
        """
        # Проверяем базовые настройки
        if not self.enabled or not self.bot_token or not self.chat_id:
            return False

        # Отправляем только ERROR и CRITICAL
        if record.levelno < logging.ERROR:
            return False

        # Rate limiting - не более N сообщений в час
        now = datetime.now()
        self.sent_messages = [
            msg_time
            for msg_time in self.sent_messages
            if (now - msg_time).seconds < 3600
        ]

        if len(self.sent_messages) >= self.max_messages_per_hour:
            return False

        # Группировка одинаковых ошибок
        error_key = self._get_error_key(record)
        if error_key in self.message_cache:
            last_sent = self.message_cache[error_key]
            # Не отправляем одинаковые ошибки чаще чем раз в 10 минут
            if (now - last_sent).seconds < 600:
                return False

        return True

    def _get_error_key(self, record):
        """
        Создает ключ для группировки одинаковых ошибок
        """
        # Используем имя модуля + тип исключения + первую строку сообщения
        key_parts = [
            record.module or "unknown",
            getattr(record, "exc_info", [None, None, None])[0].__name__
            if record.exc_info and record.exc_info[0]
            else "NoException",
            record.getMessage().split("\n")[0][:100],  # Первые 100 символов
        ]
        return "|".join(str(part) for part in key_parts)

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
                    f"🌐 URL: {request.get_full_path()[:100]}",
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

        message = "\n".join(message_parts)
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
        """
        Обрезает длинный текст, сохраняя начало и конец.
        Полезно для traceback, где конец содержит тип/сообщение исключения.
        """
        if text is None:
            return ""

        text = str(text)
        if max_length is None or max_length <= 0 or len(text) <= max_length:
            return text

        marker = str(marker)

        # Если лимит слишком мал, отдаем хвост (обычно там самая ценная часть traceback).
        if max_length <= len(marker) + 10:
            return text[-max_length:]

        available = max_length - len(marker)
        tail_len = int(available * tail_ratio)
        head_len = available - tail_len

        # Защита от некорректных ratio/округления
        if head_len < 1:
            head_len = 1
            tail_len = available - head_len
        if tail_len < 1:
            tail_len = 1
            head_len = available - tail_len

        return text[:head_len] + marker + text[-tail_len:]

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
        except:
            return "unknown"

    def _send_message_async(self, message):
        """
        Отправляет сообщение в Telegram + VK через единую утилиту.

        Имя _async — историческое (раньше тут был Thread). Сейчас
        синхронно, делегируем в notifications.send_to_all которая
        отправляет VK первым (см. notifications.py docstring).

        После успешной TG-отправки обновляет sent_messages для rate-limit.
        """
        result = send_to_all(message)
        if result.get("telegram"):
            self.sent_messages.append(datetime.now())


class TelegramErrorNotifier:
    """
    Утилитный класс для отправки кастомных уведомлений об ошибках
    """

    @staticmethod
    def notify_critical_error(title, message, details=None):
        """
        Отправляет кастомное уведомление о критической ошибке
        """
        handler = TelegramHandler()

        if not handler.enabled:
            return False

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

        # Синхронная отправка (внутри: VK сначала, потом Telegram).
        # Раньше был Thread(daemon=True), но при вызове из management
        # command'ов он убивался до отправки — см. emit() docstring.
        handler._send_message_async(formatted_message)
        return True

    @staticmethod
    def notify_system_health(status, metrics=None):
        """
        Отправляет уведомление о состоянии системы
        """
        handler = TelegramHandler()

        if not handler.enabled:
            return False

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

        # Синхронная отправка (внутри: VK сначала, потом Telegram).
        # Раньше был Thread(daemon=True), но при вызове из management
        # command'ов он убивался до отправки — см. emit() docstring.
        handler._send_message_async(formatted_message)
        return True
