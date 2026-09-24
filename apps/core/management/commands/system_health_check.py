"""
Django management команда для проверки состояния системы и отправки уведомлений
"""
import json
import os
import psutil
import logging
from datetime import datetime, timezone
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from apps.core.telegram_handler import TelegramErrorNotifier


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Проверяет состояние системы и отправляет уведомления в Telegram"

    # Ключ в Redis (тот же инстанс, что у Celery broker/rate-limit — см.
    # apps.core.notifications._get_redis) для статуса, о котором уже
    # отправлено уведомление. Cron дёргает эту команду новым процессом
    # каждые 30 минут, поэтому in-memory состояние между тиками не
    # переживает — нужно что-то внешнее и общее для всех воркеров.
    HEALTH_STATUS_REDIS_KEY = "health_check:last_notified_status"

    def add_arguments(self, parser):
        parser.add_argument(
            "--notify-telegram",
            action="store_true",
            help=(
                "Отправить результат в Telegram. По умолчанию шлёт ТОЛЬКО "
                "при смене статуса относительно прошлого уведомления "
                "(healthy↔warning↔critical) — чтобы одна проблема не "
                "превращалась в десятки одинаковых сообщений каждые "
                "30 минут, пока её не починят. Используй --notify-always "
                "чтобы слать в любом случае."
            ),
        )
        parser.add_argument(
            "--notify-vk",
            action="store_true",
            help=(
                "Отправить результат в VK. По умолчанию шлёт только "
                "при смене статуса (см. --notify-telegram)."
            ),
        )
        parser.add_argument(
            "--notify-always",
            action="store_true",
            help=(
                "Слать уведомление в TG/VK даже когда всё healthy. "
                "По умолчанию healthy-статус молчит."
            ),
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
        parser.add_argument(
            "--check-backups",
            action="store_true",
            help=(
                "Проверить свежесть последнего backup-прогона (P1-08 dead man's "
                "switch): читает last_status.json (контракт P0-08) для DB и media "
                "и сигнализирует warning, если прогона нет, он протух или "
                "result != ok."
            ),
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🔍 Проверка состояния системы"))
        self.stdout.write("")

        # Определяем какие проверки выполнять
        checks_to_run = []

        if options["check_all"]:
            checks_to_run = ["db", "disk", "memory", "backups"]
        else:
            if options["check_db"]:
                checks_to_run.append("db")
            if options["check_disk"]:
                checks_to_run.append("disk")
            if options["check_memory"]:
                checks_to_run.append("memory")
            if options["check_backups"]:
                checks_to_run.append("backups")

        if not checks_to_run:
            checks_to_run = [
                "db",
                "disk",
                "memory",
                "backups",
            ]  # По умолчанию все проверки

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
            elif check == "backups":
                results["backup db"] = self._check_backup_freshness(
                    label="DB backup",
                    subdir="database",
                    max_age_hours=26,
                )
                results["backup media"] = self._check_backup_freshness(
                    label="Media backup",
                    subdir="media",
                    max_age_hours=192,  # 8 суток — недельный цикл + запас
                )

        # Определяем общий статус
        for check_name, check_result in results.items():
            if check_result["status"] == "critical":
                overall_status = "critical"
                break
            elif check_result["status"] == "warning" and overall_status == "healthy":
                overall_status = "warning"

        # Выводим результаты
        self._display_results(results, overall_status)

        # Уведомляем только при смене статуса относительно прошлого
        # уведомления (2026-09-24) — раньше слали одно и то же предупреждение
        # каждые 30 минут, пока проблему не устраняли: один незамеченный
        # сбой на несколько часов превращался в десятки одинаковых сообщений
        # (так и было с P0-08 last_status.json для media — 19 подряд).
        notify_requested = options["notify_telegram"] or options["notify_vk"]
        should_notify = self._resolve_notify_decision(
            overall_status, notify_requested, options["notify_always"]
        )

        if options["notify_telegram"] and should_notify:
            self._send_telegram_notification(results, overall_status)
        elif options["notify_telegram"]:
            self.stdout.write(
                f"ℹ️  Status={overall_status} не изменился с прошлого "
                "уведомления, Telegram-уведомление пропущено "
                "(используй --notify-always чтобы слать всегда)"
            )

        if options["notify_vk"] and should_notify:
            self._send_vk_notification(results, overall_status)
        elif options["notify_vk"]:
            self.stdout.write(
                f"ℹ️  Status={overall_status} не изменился с прошлого "
                "уведомления, VK-уведомление пропущено "
                "(используй --notify-always чтобы слать всегда)"
            )

        if notify_requested and should_notify:
            self._set_last_notified_status(overall_status)

        # Логируем критические проблемы
        if overall_status == "critical":
            critical_issues = [
                f"{name}: {result['message']}"
                for name, result in results.items()
                if result["status"] == "critical"
            ]
            logger.critical(f"System health check failed: {'; '.join(critical_issues)}")

    def _resolve_notify_decision(self, overall_status, notify_requested, notify_always):
        """
        Решает, нужно ли слать уведомление в этом прогоне.

        notify_always=True — всегда да (ручная диагностика/проверка канала).
        Истории нет (первый прогон вообще, либо Redis недоступен — тот же
        fail-open, что и в notifications.check_rate_limit) — прежнее
        поведение по умолчанию: молчим на healthy, уведомляем один раз на
        первую же проблему.
        Иначе — только если overall_status реально отличается от того, о
        котором уведомили в прошлый раз.
        """
        if notify_always:
            return True
        if not notify_requested:
            return False

        last_status = self._get_last_notified_status()
        if last_status is None:
            return overall_status != "healthy"
        return overall_status != last_status

    def _get_last_notified_status(self):
        """Читает из Redis статус последнего отправленного уведомления.
        None — истории нет или Redis недоступен (fail-open в handle())."""
        from apps.core.notifications import _get_redis

        r = _get_redis()
        if r is None:
            return None
        try:
            value = r.get(self.HEALTH_STATUS_REDIS_KEY)
            return value.decode("utf-8") if value else None
        except Exception as e:
            logger.warning("Redis недоступен для чтения статуса health-check: %s", e)
            return None

    def _set_last_notified_status(self, status):
        """Запоминает в Redis статус, о котором только что уведомили."""
        from apps.core.notifications import _get_redis

        r = _get_redis()
        if r is None:
            return
        try:
            r.set(self.HEALTH_STATUS_REDIS_KEY, status)
        except Exception as e:
            logger.warning("Redis недоступен для записи статуса health-check: %s", e)

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

    def _resolve_backup_status_dir(self, subdir):
        """
        Определяет каталог, где `scripts/backup-status.sh` (контракт P0-08)
        пишет `last_status.json` для указанного типа бэкапа.

        `subdir` — "database" или "media", как в `apps.reports.views`
        (`_get_backup_search_dirs`), логику которой этот метод сознательно
        не дублирует целиком — здесь не нужен glob-поиск файла бэкапа,
        только каталог со статусом. Использует те же settings-переменные,
        чтобы не завести второй источник правды по путям.
        """
        explicit_dir = (
            settings.BACKUP_DB_DIR
            if subdir == "database"
            else settings.BACKUP_MEDIA_DIR
        )

        candidates = []
        if explicit_dir:
            candidates.append(explicit_dir)
        if settings.BACKUP_BASE_DIR:
            candidates.append(os.path.join(settings.BACKUP_BASE_DIR, subdir))
        candidates.append(os.path.join("/app/server_backups", subdir))
        candidates.append(
            os.path.expanduser(os.path.join("~/insurance_broker_backups", subdir))
        )

        for candidate in candidates:
            try:
                if candidate and os.path.isdir(candidate):
                    return candidate
            except OSError:
                continue
        return None

    def _check_backup_freshness(self, label, subdir, max_age_hours):
        """
        P1-08 dead man's switch: бэкап-скрипты (P0-08) сами пишут
        `last_status.json` с итогом каждого прогона. Здесь мы его только
        читаем — пересчитывать required-стадии не нужно, поле `result`
        в файле уже вычислено `evaluate_backup_result()` в
        `scripts/backup-status.sh` с учётом текущих
        `DB_REQUIRED_STAGES`/`MEDIA_REQUIRED_STAGES`.

        Возвращает "warning" (не "critical") при отсутствии/порче/протухании
        файла или result != "ok" — сам сайт при этом не сломан, но
        backup-контур мог замолчать никем не замеченным.
        """
        backup_dir = self._resolve_backup_status_dir(subdir)
        if not backup_dir:
            return {
                "status": "warning",
                "message": f"{label}: backup status directory not found",
                "details": (
                    "Ни один из известных путей (BACKUP_DB_DIR/BACKUP_MEDIA_DIR, "
                    "BACKUP_BASE_DIR, /app/server_backups) не существует"
                ),
            }

        status_path = os.path.join(backup_dir, "last_status.json")
        if not os.path.isfile(status_path):
            return {
                "status": "warning",
                "message": f"{label}: last_status.json not found",
                "details": (
                    f"Ожидался {status_path} (контракт P0-08) — "
                    "nightly-бэкап этого типа мог ни разу не запуститься"
                ),
            }

        try:
            with open(status_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            return {
                "status": "warning",
                "message": f"{label}: last_status.json unreadable/corrupt",
                "details": str(exc),
            }

        ts_raw = data.get("ts")
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            return {
                "status": "warning",
                "message": f"{label}: last_status.json has invalid 'ts'",
                "details": f"ts={ts_raw!r}",
            }

        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        result = data.get("result")
        file_name = data.get("file")

        if result != "ok":
            return {
                "status": "warning",
                "message": f"{label}: last run result={result!r} (exit={data.get('exit')})",
                "details": f"file={file_name}, ts={ts_raw}",
            }

        if age_hours > max_age_hours:
            return {
                "status": "warning",
                "message": (
                    f"{label}: last successful run is {age_hours:.1f}h old "
                    f"(> {max_age_hours}h)"
                ),
                "details": f"file={file_name}, ts={ts_raw}",
            }

        required = data.get("required")
        required_display = (
            ",".join(required) if isinstance(required, list) else str(required)
        )

        return {
            "status": "healthy",
            "message": f"{label}: fresh, result=ok ({age_hours:.1f}h ago)",
            "details": f"file={file_name}, required={required_display}",
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
