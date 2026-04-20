"""
Django management команда для проверки состояния системы и отправки уведомлений
"""
import os
import psutil
import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from apps.core.telegram_handler import TelegramErrorNotifier


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Проверяет состояние системы и отправляет уведомления в Telegram"

    def add_arguments(self, parser):
        parser.add_argument(
            "--notify-telegram",
            action="store_true",
            help="Отправить результат проверки в Telegram",
        )
        parser.add_argument(
            "--notify-vk",
            action="store_true",
            help="Отправить результат проверки в VK",
        )
        parser.add_argument(
            "--check-all",
            action="store_true",
            help="Выполнить все проверки",
        )
        parser.add_argument(
            "--check-db",
            action="store_true",
            help="Проверить подключение к базе данных",
        )
        parser.add_argument(
            "--check-disk",
            action="store_true",
            help="Проверить использование диска",
        )
        parser.add_argument(
            "--check-memory",
            action="store_true",
            help="Проверить использование памяти",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🔍 Проверка состояния системы"))
        self.stdout.write("")

        # Определяем какие проверки выполнять
        checks_to_run = []

        if options["check_all"]:
            checks_to_run = ["db", "disk", "memory"]
        else:
            if options["check_db"]:
                checks_to_run.append("db")
            if options["check_disk"]:
                checks_to_run.append("disk")
            if options["check_memory"]:
                checks_to_run.append("memory")

        if not checks_to_run:
            checks_to_run = ["db", "disk", "memory"]  # По умолчанию все проверки

        # Выполняем проверки
        results = {}
        overall_status = "healthy"

        for check in checks_to_run:
            if check == "db":
                results["database"] = self._check_database()
            elif check == "disk":
                results["disk"] = self._check_disk_usage()
            elif check == "memory":
                results["memory"] = self._check_memory_usage()

        # Определяем общий статус
        for check_name, check_result in results.items():
            if check_result["status"] == "critical":
                overall_status = "critical"
                break
            elif check_result["status"] == "warning" and overall_status == "healthy":
                overall_status = "warning"

        # Выводим результаты
        self._display_results(results, overall_status)

        # Отправляем уведомления если нужно
        if options["notify_telegram"]:
            self._send_telegram_notification(results, overall_status)

        if options["notify_vk"]:
            self._send_vk_notification(results, overall_status)

        # Логируем критические проблемы
        if overall_status == "critical":
            critical_issues = [
                f"{name}: {result['message']}"
                for name, result in results.items()
                if result["status"] == "critical"
            ]
            logger.critical(f"System health check failed: {'; '.join(critical_issues)}")

    def _check_database(self):
        """Проверяет подключение к базе данных"""
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()

            if result and result[0] == 1:
                return {
                    "status": "healthy",
                    "message": "Database connection OK",
                    "details": f"Engine: {connection.vendor}",
                }
            else:
                return {
                    "status": "critical",
                    "message": "Database query failed",
                    "details": "SELECT 1 returned unexpected result",
                }

        except Exception as e:
            return {
                "status": "critical",
                "message": f"Database connection failed: {str(e)}",
                "details": str(e),
            }

    def _check_disk_usage(self):
        """Проверяет использование диска"""
        try:
            # Проверяем корневую файловую систему
            disk_usage = psutil.disk_usage("/")
            used_percent = (disk_usage.used / disk_usage.total) * 100

            free_gb = disk_usage.free / (1024**3)
            used_gb = disk_usage.used / (1024**3)
            total_gb = disk_usage.total / (1024**3)

            if used_percent > 90:
                status = "critical"
                message = f"Disk usage critical: {used_percent:.1f}% used"
            elif used_percent > 80:
                status = "warning"
                message = f"Disk usage high: {used_percent:.1f}% used"
            else:
                status = "healthy"
                message = f"Disk usage normal: {used_percent:.1f}% used"

            return {
                "status": status,
                "message": message,
                "details": f"{used_gb:.1f}GB used / {total_gb:.1f}GB total ({free_gb:.1f}GB free)",
            }

        except Exception as e:
            return {
                "status": "critical",
                "message": f"Disk check failed: {str(e)}",
                "details": str(e),
            }

    def _check_memory_usage(self):
        """Проверяет использование памяти"""
        try:
            memory = psutil.virtual_memory()
            used_percent = memory.percent

            available_gb = memory.available / (1024**3)
            used_gb = memory.used / (1024**3)
            total_gb = memory.total / (1024**3)

            if used_percent > 90:
                status = "critical"
                message = f"Memory usage critical: {used_percent:.1f}% used"
            elif used_percent > 80:
                status = "warning"
                message = f"Memory usage high: {used_percent:.1f}% used"
            else:
                status = "healthy"
                message = f"Memory usage normal: {used_percent:.1f}% used"

            return {
                "status": status,
                "message": message,
                "details": f"{used_gb:.1f}GB used / {total_gb:.1f}GB total ({available_gb:.1f}GB available)",
            }

        except Exception as e:
            return {
                "status": "critical",
                "message": f"Memory check failed: {str(e)}",
                "details": str(e),
            }

    def _display_results(self, results, overall_status):
        """Выводит результаты проверок в консоль"""
        status_colors = {
            "healthy": self.style.SUCCESS,
            "warning": self.style.WARNING,
            "critical": self.style.ERROR,
        }

        status_emojis = {"healthy": "✅", "warning": "⚠️", "critical": "❌"}

        # Общий статус
        color_func = status_colors.get(overall_status, self.style.SUCCESS)
        emoji = status_emojis.get(overall_status, "❓")

        self.stdout.write("")
        self.stdout.write(
            color_func(f"{emoji} Overall Status: {overall_status.upper()}")
        )
        self.stdout.write("")

        # Детали по каждой проверке
        for check_name, result in results.items():
            color_func = status_colors.get(result["status"], self.style.SUCCESS)
            emoji = status_emojis.get(result["status"], "❓")

            self.stdout.write(
                color_func(f'{emoji} {check_name.title()}: {result["message"]}')
            )
            if result.get("details"):
                self.stdout.write(f'   Details: {result["details"]}')

        self.stdout.write("")

    def _send_telegram_notification(self, results, overall_status):
        """Отправляет уведомление в Telegram"""
        self.stdout.write("📤 Отправка уведомления в Telegram...")

        # Формируем метрики для отправки
        metrics = {}
        for check_name, result in results.items():
            metrics[check_name.title()] = f"{result['status']} - {result['message']}"

        success = TelegramErrorNotifier.notify_system_health(overall_status, metrics)

        if success:
            self.stdout.write(self.style.SUCCESS("✅ Уведомление отправлено в Telegram"))
        else:
            self.stdout.write(
                self.style.WARNING("⚠️ Не удалось отправить уведомление в Telegram")
            )

    def _send_vk_notification(self, results, overall_status):
        """Отправляет уведомление о состоянии системы в VK"""
        from apps.core.vk_handler import send_vk_message
        from datetime import datetime, timezone, timedelta

        self.stdout.write("📤 Отправка уведомления в VK...")

        status_emoji = (
            "✅"
            if overall_status == "healthy"
            else "⚠️"
            if overall_status == "warning"
            else "❌"
        )
        moscow_tz = timezone(timedelta(hours=3))
        timestamp = datetime.now(moscow_tz).strftime("%Y-%m-%d %H:%M:%S MSK")

        message_parts = [
            f"{status_emoji} System Health Check",
            "",
            f"🕐 Time: {timestamp}",
            f"📊 Status: {overall_status.upper()}",
            "",
            "📈 Metrics:",
        ]
        for check_name, result in results.items():
            message_parts.append(
                f"• {check_name.title()}: {result['status']} — {result['message']}"
            )

        success = send_vk_message("\n".join(message_parts))

        if success:
            self.stdout.write(self.style.SUCCESS("✅ Уведомление отправлено в VK"))
        else:
            self.stdout.write(
                self.style.WARNING("⚠️ Не удалось отправить уведомление в VK")
            )
