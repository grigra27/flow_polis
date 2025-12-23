"""
Django management команда для отправки ежедневного дайджеста в Telegram
"""
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from auditlog.models import LogEntry
from apps.accounts.models import LoginAttempt
from apps.policies.models import Policy, PaymentSchedule


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Отправляет ежедневный дайджест в Telegram"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Дата для дайджеста в формате YYYY-MM-DD (по умолчанию вчера)",
        )
        parser.add_argument(
            "--test",
            action="store_true",
            help="Тестовый режим - отправить дайджест за последние 2 часа",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("📊 Генерация ежедневного дайджеста"))

        # Определяем период для анализа
        if options["test"]:
            # Тестовый режим - последние 2 часа
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=2)
            period_name = f"последние 2 часа (тест)"
        elif options["date"]:
            # Конкретная дата
            try:
                target_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
                start_time = datetime.combine(target_date, datetime.min.time())
                end_time = start_time + timedelta(days=1)
                period_name = target_date.strftime("%d.%m.%Y")
            except ValueError:
                self.stdout.write(
                    self.style.ERROR("Неверный формат даты. Используйте YYYY-MM-DD")
                )
                return
        else:
            # По умолчанию - вчерашний день
            yesterday = datetime.now().date() - timedelta(days=1)
            start_time = datetime.combine(yesterday, datetime.min.time())
            end_time = start_time + timedelta(days=1)
            period_name = yesterday.strftime("%d.%m.%Y")

        self.stdout.write(f"Период: {period_name}")
        self.stdout.write(f"С: {start_time}")
        self.stdout.write(f"По: {end_time}")

        try:
            # Собираем данные
            logins_data = self._get_logins_data(start_time, end_time)
            policies_data = self._get_policies_data(start_time, end_time)

            # Формируем сообщение
            message = self._format_message(period_name, logins_data, policies_data)

            # Отправляем в Telegram через telegram-notify.sh
            full_message = f"📊 Дайджест за {period_name}\n\n{message}"
            success = self._send_telegram_message(full_message)

            if success:
                self.stdout.write(self.style.SUCCESS("✅ Дайджест отправлен в Telegram"))
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️ Не удалось отправить дайджест в Telegram")
                )

        except Exception as e:
            logger.exception(f"Ошибка при генерации дайджеста: {e}")
            self.stdout.write(self.style.ERROR(f"❌ Ошибка: {e}"))

    def _send_telegram_message(self, message):
        """Отправляет сообщение в Telegram через Python (без curl)"""
        try:
            from urllib.parse import urlencode
            from urllib.request import urlopen, Request
            from decouple import config

            # Получаем настройки Telegram
            bot_token = config("TELEGRAM_BOT_TOKEN", default="")
            chat_id = config("TELEGRAM_CHAT_ID", default="")
            enabled = config("TELEGRAM_ENABLED", default=False, cast=bool)

            if not enabled or not bot_token or not chat_id:
                logger.error("Telegram not configured")
                return False

            # Подготавливаем данные
            data = {
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            }

            # Кодируем данные
            encoded_data = urlencode(data).encode("utf-8")

            # Создаем запрос
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            request = Request(
                api_url,
                data=encoded_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # Отправляем запрос
            with urlopen(request, timeout=10) as response:
                import json

                result = json.loads(response.read().decode("utf-8"))

                if result.get("ok"):
                    return True
                else:
                    logger.error(f"Telegram API error: {result}")
                    return False

        except Exception as e:
            logger.error(f"Error sending telegram message: {e}")
            return False

    def _get_logins_data(self, start_time, end_time):
        """Получает данные о логинах пользователей"""
        # Успешные логины за период
        successful_logins = (
            LoginAttempt.objects.filter(
                attempt_time__gte=start_time, attempt_time__lt=end_time, success=True
            )
            .select_related()
            .order_by("attempt_time")
        )

        logins_list = []
        for login in successful_logins:
            # Конвертируем в московское время
            moscow_tz = timezone.get_current_timezone()
            moscow_time = login.attempt_time.astimezone(moscow_tz)

            logins_list.append(
                {
                    "time": moscow_time.strftime("%H:%M"),
                    "username": login.username,
                    "ip": login.ip_address,
                }
            )

        return logins_list

    def _get_policies_data(self, start_time, end_time):
        """Получает данные об изменениях полисов"""
        # Получаем ContentType для моделей
        policy_ct = ContentType.objects.get_for_model(Policy)
        payment_ct = ContentType.objects.get_for_model(PaymentSchedule)

        # Изменения полисов
        policy_changes = (
            LogEntry.objects.filter(
                content_type=policy_ct,
                timestamp__gte=start_time,
                timestamp__lt=end_time,
            )
            .select_related("actor")
            .order_by("timestamp")
        )

        # Изменения платежей
        payment_changes = (
            LogEntry.objects.filter(
                content_type=payment_ct,
                timestamp__gte=start_time,
                timestamp__lt=end_time,
            )
            .select_related("actor")
            .order_by("timestamp")
        )

        # Обрабатываем изменения полисов
        policies_data = {"created": [], "updated": [], "payment_changes": []}

        # Группируем изменения полисов по ID
        policy_changes_by_id = {}
        for change in policy_changes:
            policy_id = change.object_pk
            if policy_id not in policy_changes_by_id:
                policy_changes_by_id[policy_id] = []
            policy_changes_by_id[policy_id].append(change)

        # Обрабатываем каждый полис
        for policy_id, changes in policy_changes_by_id.items():
            try:
                policy = Policy.objects.select_related("client", "insurer").get(
                    pk=policy_id
                )

                # Определяем тип изменения (создание или обновление)
                has_create = any(
                    change.action == LogEntry.Action.CREATE for change in changes
                )
                has_update = any(
                    change.action == LogEntry.Action.UPDATE for change in changes
                )

                policy_info = {
                    "policy": policy,
                    "url": f"https://polis.insflow.ru/policies/{policy.pk}/",
                    "changes": changes,
                }

                if has_create:
                    policies_data["created"].append(policy_info)
                elif has_update:
                    policies_data["updated"].append(policy_info)

            except Policy.DoesNotExist:
                # Полис был удален
                continue

        # Обрабатываем изменения платежей
        payment_changes_by_policy = {}
        for change in payment_changes:
            try:
                payment = PaymentSchedule.objects.select_related(
                    "policy__client", "policy__insurer"
                ).get(pk=change.object_pk)
                policy_id = payment.policy.pk

                if policy_id not in payment_changes_by_policy:
                    payment_changes_by_policy[policy_id] = {
                        "policy": payment.policy,
                        "changes": [],
                    }
                payment_changes_by_policy[policy_id]["changes"].append(
                    {"payment": payment, "change": change}
                )

            except PaymentSchedule.DoesNotExist:
                continue

        # Добавляем изменения платежей (только если сам полис не менялся)
        for policy_id, payment_data in payment_changes_by_policy.items():
            if str(policy_id) not in policy_changes_by_id:  # Полис сам не менялся
                payment_data["url"] = f"https://polis.insflow.ru/policies/{policy_id}/"
                policies_data["payment_changes"].append(payment_data)

        return policies_data

    def _format_message(self, period_name, logins_data, policies_data):
        """Форматирует сообщение для отправки"""
        message_parts = []

        # Логины пользователей
        if logins_data:
            message_parts.append("👥 ЛОГИНЫ:")
            for login in logins_data:
                message_parts.append(f"• {login['time']} - {login['username']}")
        else:
            message_parts.append("👥 ЛОГИНЫ: нет активности")

        message_parts.append("")  # Пустая строка

        # Полисы
        message_parts.append("📋 ПОЛИСЫ:")

        # Созданные полисы
        if policies_data["created"]:
            message_parts.append("")
            message_parts.append("🆕 Созданы:")
            for item in policies_data["created"]:
                policy = item["policy"]
                message_parts.append(
                    f"• {policy.policy_number} | {policy.client.client_name} | {policy.insurer.name}"
                )
                message_parts.append(f"  👉 {item['url']}")

        # Обновленные полисы
        if policies_data["updated"]:
            message_parts.append("")
            message_parts.append("✏️ Изменены:")
            for item in policies_data["updated"]:
                policy = item["policy"]
                message_parts.append(
                    f"• {policy.policy_number} | {policy.client.client_name} | {policy.insurer.name}"
                )
                message_parts.append(f"  👉 {item['url']}")

        # Изменения платежей
        if policies_data["payment_changes"]:
            message_parts.append("")
            message_parts.append("💰 Изменены платежи:")
            for item in policies_data["payment_changes"]:
                policy = item["policy"]
                message_parts.append(
                    f"• {policy.policy_number} | {policy.client.client_name} | {policy.insurer.name}"
                )
                message_parts.append(f"  👉 {item['url']}")
                # Показываем количество измененных платежей
                changes_count = len(item["changes"])
                message_parts.append(f"  💳 Платежей изменено: {changes_count}")

        # Если никаких изменений не было
        if not any(
            [
                policies_data["created"],
                policies_data["updated"],
                policies_data["payment_changes"],
            ]
        ):
            message_parts.append("Изменений не было")

        return "\n".join(message_parts)
