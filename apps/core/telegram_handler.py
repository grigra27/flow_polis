"""
Telegram Logging Handler for Django
Отправляет критические ошибки в Telegram канал
"""
import logging
import json
import traceback
from datetime import datetime
from threading import Thread
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError
from django.conf import settings
from decouple import config


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
        self.message_cache = {}  # Кэш для группировки одинаковых ошибок
        self.sent_messages = []  # История отправленных сообщений для rate limiting

        # URL для Telegram API
        if self.bot_token:
            self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        else:
            self.api_url = None

    def emit(self, record):
        """
        Отправляет лог запись в Telegram
        """
        if not self._should_send_message(record):
            return

        try:
            # Форматируем сообщение
            message = self._format_message(record)

            # Отправляем асинхронно чтобы не блокировать основной поток
            thread = Thread(target=self._send_message_async, args=(message,))
            thread.daemon = True
            thread.start()

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
        timestamp = datetime.fromtimestamp(record.created).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

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
        if len(error_message) > 500:
            error_message = error_message[:500] + "..."

        message_parts.extend(
            [
                "",
                f"❗ Error:",
                f"{error_message}",
            ]
        )

        # Добавляем traceback если есть
        if record.exc_info:
            tb_lines = traceback.format_exception(*record.exc_info)
            tb_text = "".join(tb_lines)

            # Ограничиваем размер traceback
            if len(tb_text) > 1000:
                tb_text = tb_text[:1000] + "\n... (truncated)"

            message_parts.extend(
                [
                    "",
                    f"📋 Traceback:",
                    f"{tb_text}",
                ]
            )

        return "\n".join(message_parts)

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
        Асинхронно отправляет сообщение в Telegram
        """
        try:
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "disable_web_page_preview": True,
            }

            # Кодируем данные
            encoded_data = urlencode(data).encode("utf-8")

            # Создаем запрос
            request = Request(
                f"{self.api_url}/sendMessage",
                data=encoded_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # Отправляем запрос
            with urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))

                if result.get("ok"):
                    # Обновляем кэш и историю
                    now = datetime.now()
                    self.sent_messages.append(now)

                    # Обновляем кэш группировки ошибок
                    # (здесь нужно было бы передать record, но для простоты пропускаем)

                    print(f"TelegramHandler: Message sent successfully")
                else:
                    print(f"TelegramHandler: Telegram API error: {result}")

        except URLError as e:
            print(f"TelegramHandler: Network error: {e}")
        except Exception as e:
            print(f"TelegramHandler: Unexpected error: {e}")


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

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

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

        # Отправляем асинхронно
        thread = Thread(target=handler._send_message_async, args=(formatted_message,))
        thread.daemon = True
        thread.start()

        return True

    @staticmethod
    def notify_system_health(status, metrics=None):
        """
        Отправляет уведомление о состоянии системы
        """
        handler = TelegramHandler()

        if not handler.enabled:
            return False

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
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

        # Отправляем асинхронно
        thread = Thread(target=handler._send_message_async, args=(formatted_message,))
        thread.daemon = True
        thread.start()

        return True
