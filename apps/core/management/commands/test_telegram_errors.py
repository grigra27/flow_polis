"""
Django management команда для тестирования Telegram уведомлений об ошибках
"""
import logging
from django.core.management.base import BaseCommand
from apps.core.telegram_handler import TelegramErrorNotifier


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Тестирует отправку уведомлений об ошибках в Telegram"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test-error",
            action="store_true",
            help="Отправить тестовую ошибку через logging",
        )
        parser.add_argument(
            "--test-critical",
            action="store_true",
            help="Отправить тестовую критическую ошибку",
        )
        parser.add_argument(
            "--test-exception",
            action="store_true",
            help="Отправить тестовое исключение с traceback",
        )
        parser.add_argument(
            "--test-custom",
            action="store_true",
            help="Отправить кастомное уведомление",
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("🧪 Тестирование Telegram уведомлений об ошибках")
        )
        self.stdout.write("")

        if options["test_error"]:
            self._test_error()
        elif options["test_critical"]:
            self._test_critical()
        elif options["test_exception"]:
            self._test_exception()
        elif options["test_custom"]:
            self._test_custom()
        else:
            self._show_usage()

    def _test_error(self):
        """Тестирует отправку ERROR уровня"""
        self.stdout.write("📤 Отправка тестовой ошибки ERROR уровня...")
        logger.error(
            "Тестовая ошибка ERROR: Это тестовое сообщение для проверки Telegram уведомлений"
        )
        self.stdout.write(
            self.style.SUCCESS("✅ Ошибка отправлена. Проверьте Telegram канал.")
        )

    def _test_critical(self):
        """Тестирует отправку CRITICAL уровня"""
        self.stdout.write("📤 Отправка критической ошибки CRITICAL уровня...")
        logger.critical(
            "Тестовая критическая ошибка: Система обнаружила критическую проблему"
        )
        self.stdout.write(
            self.style.SUCCESS(
                "✅ Критическая ошибка отправлена. Проверьте Telegram канал."
            )
        )

    def _test_exception(self):
        """Тестирует отправку исключения с traceback"""
        self.stdout.write("📤 Отправка тестового исключения с traceback...")
        try:
            # Намеренно вызываем ошибку
            result = 1 / 0
        except ZeroDivisionError as e:
            logger.exception("Тестовое исключение: Произошла ошибка деления на ноль")

        self.stdout.write(
            self.style.SUCCESS("✅ Исключение отправлено. Проверьте Telegram канал.")
        )

    def _test_custom(self):
        """Тестирует кастомное уведомление"""
        self.stdout.write("📤 Отправка кастомного уведомления...")

        TelegramErrorNotifier.notify_critical_error(
            title="Test Custom Notification",
            message="Это кастомное тестовое уведомление отправленное напрямую через TelegramErrorNotifier",
            details={
                "test_parameter": "test_value",
                "status": "testing",
                "component": "telegram_handler",
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                "✅ Кастомное уведомление отправлено. Проверьте Telegram канал."
            )
        )

    def _show_usage(self):
        """Показывает примеры использования"""
        self.stdout.write(self.style.WARNING("Укажите тип теста:"))
        self.stdout.write("")
        self.stdout.write("  --test-error       Тестовая ошибка ERROR уровня")
        self.stdout.write("  --test-critical    Тестовая критическая ошибка")
        self.stdout.write("  --test-exception   Тестовое исключение с traceback")
        self.stdout.write("  --test-custom      Кастомное уведомление")
        self.stdout.write("")
        self.stdout.write("Примеры:")
        self.stdout.write("  python manage.py test_telegram_errors --test-error")
        self.stdout.write("  python manage.py test_telegram_errors --test-exception")
