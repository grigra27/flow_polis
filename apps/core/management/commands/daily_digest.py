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
                start_time = timezone.make_aware(
                    datetime.combine(target_date, datetime.min.time())
                )
                end_time = start_time + timedelta(days=1)
                period_name = target_date.strftime("%d.%m.%Y")
            except ValueError:
                self.stdout.write(
                    self.style.ERROR("Неверный формат даты. Используйте YYYY-MM-DD")
                )
                return
        else:
            # По умолчанию - вчерашний день
            yesterday = timezone.now().date() - timedelta(days=1)
            start_time = timezone.make_aware(
                datetime.combine(yesterday, datetime.min.time())
            )
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

    def _escape_markdown_text(self, text):
        """Экранирует специальные символы для Markdown (только для обычного текста)"""
        if not text:
            return text

        # Экранируем только критически важные символы
        escape_chars = ["_", "*", "`", "[", "]"]
        result = str(text)
        for char in escape_chars:
            result = result.replace(char, f"\\{char}")
        return result

    def _clean_policy_number_for_link(self, policy_number):
        """Очищает номер ДФА для использования в Markdown ссылке"""
        if not policy_number:
            return policy_number

        # Заменяем проблемные символы в номерах ДФА для ссылок
        cleaned = str(policy_number)

        # Убираем лишние пробелы и заменяем на дефисы
        cleaned = cleaned.strip()

        # Заменяем запятые и точки на дефисы
        cleaned = cleaned.replace(",", "-").replace(".", "-")

        # Заменяем множественные пробелы на один дефис
        import re

        cleaned = re.sub(r"\s+", "-", cleaned)

        # Убираем множественные дефисы
        cleaned = re.sub(r"-+", "-", cleaned)

        # Убираем дефисы в начале и конце
        cleaned = cleaned.strip("-")

        return cleaned

    def _get_logins_data(self, start_time, end_time):
        """Получает данные о логинах пользователей"""
        print(f"DEBUG: Getting logins from {start_time} to {end_time}")

        # Успешные логины за период
        successful_logins = (
            LoginAttempt.objects.filter(
                attempt_time__gte=start_time, attempt_time__lt=end_time, success=True
            )
            .select_related()
            .order_by("attempt_time")
        )

        print(f"DEBUG: Found {successful_logins.count()} successful logins")

        logins_list = []
        for i, login in enumerate(successful_logins):
            print(
                f"DEBUG: Raw login {i+1}: username='{login.username}', time={login.attempt_time}"
            )

            # Конвертируем в московское время
            moscow_tz = timezone.get_current_timezone()
            moscow_time = login.attempt_time.astimezone(moscow_tz)

            login_data = {
                "time": moscow_time.strftime("%H:%M"),
                "username": login.username,
                "ip": login.ip_address,
            }

            print(f"DEBUG: Processed login {i+1}: {login_data}")
            logins_list.append(login_data)

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
        """Форматирует сообщение для отправки с отладкой"""
        print(f"DEBUG: Formatting message for period: {period_name}")
        print(f"DEBUG: Logins count: {len(logins_data)}")
        print(f"DEBUG: Policies created: {len(policies_data['created'])}")
        print(f"DEBUG: Policies updated: {len(policies_data['updated'])}")
        print(f"DEBUG: Payment changes: {len(policies_data['payment_changes'])}")

        message_parts = []

        # Логины пользователей
        if logins_data:
            message_parts.append("👥 ЛОГИНЫ:")
            for i, login in enumerate(logins_data):
                print(
                    f"DEBUG: Processing login {i+1}: '{login['username']}' at {login['time']}"
                )
                # НЕ экранируем логины - они не в ссылках и должны отображаться как есть
                login_line = f"• {login['time']} - {login['username']}"
                print(f"DEBUG: Login line: '{login_line}'")
                message_parts.append(login_line)
        else:
            message_parts.append("👥 ЛОГИНЫ: нет активности")

        message_parts.append("")  # Пустая строка

        # Полисы
        message_parts.append("📋 ПОЛИСЫ:")

        # Созданные полисы
        if policies_data["created"]:
            message_parts.append("")
            message_parts.append("🆕 Созданы:")
            for i, item in enumerate(policies_data["created"]):
                policy = item["policy"]
                print(f"DEBUG: Processing created policy {i+1}: ID={policy.pk}")

                # Используем номер ДФА если есть, иначе номер полиса
                policy_number = (
                    policy.dfa_number if policy.dfa_number else policy.policy_number
                )
                # Защита от None значений
                policy_number = policy_number or f"Policy-{policy.pk}"
                client_name = policy.client.client_name or "Неизвестный клиент"
                insurer_name = policy.insurer.insurer_name or "Неизвестная страховая"

                print(
                    f"DEBUG: Policy number: '{policy_number}' (type: {type(policy_number)})"
                )
                print(f"DEBUG: Client name: '{client_name}'")
                print(f"DEBUG: Insurer name: '{insurer_name}'")

                # Экранируем только имена клиентов и страховщиков (не номер ДФА в ссылке)
                client_name = self._escape_markdown_text(client_name)
                insurer_name = self._escape_markdown_text(insurer_name)

                print(f"DEBUG: Escaped client name: '{client_name}'")
                print(f"DEBUG: Escaped insurer name: '{insurer_name}'")

                # Создаем Markdown ссылку (очищаем номер ДФА для ссылки)
                cleaned_policy_number = self._clean_policy_number_for_link(
                    policy_number
                )
                policy_link = f"[{cleaned_policy_number}]({item['url']})"
                print(f"DEBUG: Policy link: '{policy_link}'")

                # Временно убираем Markdown ссылки для тестирования
                line = f"• {policy_number} | {client_name} | {insurer_name}"
                print(f"DEBUG: Final line: '{line}'")
                message_parts.append(line)
                message_parts.append(f"  🔗 {item['url']}")

        # Обновленные полисы
        if policies_data["updated"]:
            message_parts.append("")
            message_parts.append("✏️ Изменены:")
            for i, item in enumerate(policies_data["updated"]):
                policy = item["policy"]
                print(f"DEBUG: Processing updated policy {i+1}: ID={policy.pk}")

                # Используем номер ДФА если есть, иначе номер полиса
                policy_number = (
                    policy.dfa_number if policy.dfa_number else policy.policy_number
                )
                # Защита от None значений
                policy_number = policy_number or f"Policy-{policy.pk}"
                client_name = policy.client.client_name or "Неизвестный клиент"
                insurer_name = policy.insurer.insurer_name or "Неизвестная страховая"

                print(f"DEBUG: Policy number: '{policy_number}'")

                # Экранируем только имена клиентов и страховщиков (не номер ДФА в ссылке)
                client_name = self._escape_markdown_text(client_name)
                insurer_name = self._escape_markdown_text(insurer_name)

                # Создаем Markdown ссылку (очищаем номер ДФА для ссылки)
                cleaned_policy_number = self._clean_policy_number_for_link(
                    policy_number
                )
                policy_link = f"[{cleaned_policy_number}]({item['url']})"
                # Временно убираем Markdown ссылки для тестирования
                line = f"• {policy_number} | {client_name} | {insurer_name}"
                print(f"DEBUG: Updated policy line: '{line}'")
                message_parts.append(line)
                message_parts.append(f"  🔗 {item['url']}")

        # Изменения платежей
        if policies_data["payment_changes"]:
            message_parts.append("")
            message_parts.append("💰 Изменены платежи:")
            for i, item in enumerate(policies_data["payment_changes"]):
                policy = item["policy"]
                print(f"DEBUG: Processing payment change {i+1}: ID={policy.pk}")

                # Используем номер ДФА если есть, иначе номер полиса
                policy_number = (
                    policy.dfa_number if policy.dfa_number else policy.policy_number
                )
                # Защита от None значений
                policy_number = policy_number or f"Policy-{policy.pk}"
                client_name = policy.client.client_name or "Неизвестный клиент"
                insurer_name = policy.insurer.insurer_name or "Неизвестная страховая"

                print(f"DEBUG: Payment policy number: '{policy_number}'")

                # Экранируем только имена клиентов и страховщиков (не номер ДФА в ссылке)
                client_name = self._escape_markdown_text(client_name)
                insurer_name = self._escape_markdown_text(insurer_name)

                # Создаем Markdown ссылку (очищаем номер ДФА для ссылки)
                cleaned_policy_number = self._clean_policy_number_for_link(
                    policy_number
                )
                policy_link = f"[{cleaned_policy_number}]({item['url']})"
                # Временно убираем Markdown ссылки для тестирования
                line = f"• {policy_number} | {client_name} | {insurer_name}"
                print(f"DEBUG: Payment change line: '{line}'")
                message_parts.append(line)
                message_parts.append(f"  🔗 {item['url']}")

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

        final_message = "\n".join(message_parts)
        print(f"DEBUG: Final message length: {len(final_message)}")
        print(f"DEBUG: Final message preview: {repr(final_message[:300])}")

        # Показываем секцию логинов отдельно для отладки
        logins_section = []
        in_logins = False
        for line in message_parts:
            if line.startswith("👥 ЛОГИНЫ"):
                in_logins = True
                logins_section.append(line)
            elif in_logins and line.startswith("📋 ПОЛИСЫ"):
                break
            elif in_logins:
                logins_section.append(line)

        print(f"DEBUG: Logins section:")
        for line in logins_section:
            print(f"  '{line}'")

        return final_message

    def _send_telegram_message(self, message):
        """Отправляет сообщение в Telegram через Python с детальной отладкой"""
        try:
            from urllib.parse import urlencode
            from urllib.request import urlopen, Request, HTTPError
            from decouple import config
            import json

            # Получаем настройки Telegram
            bot_token = config("TELEGRAM_BOT_TOKEN", default="")
            chat_id = config("TELEGRAM_CHAT_ID", default="")
            enabled = config("TELEGRAM_ENABLED", default=False, cast=bool)

            print(
                f"DEBUG: Telegram config - enabled: {enabled}, has_token: {bool(bot_token)}, has_chat_id: {bool(chat_id)}"
            )

            if not enabled or not bot_token or not chat_id:
                logger.error("Telegram not configured")
                return False

            # Детальная отладка сообщения
            print(f"DEBUG: Message length: {len(message)}")
            print(f"DEBUG: Message preview (first 200 chars): {repr(message[:200])}")

            # Проверяем на проблемные символы
            problematic_chars = []
            for i, char in enumerate(message):
                if ord(char) > 127:  # Non-ASCII символы
                    problematic_chars.append((i, char, ord(char)))

            if problematic_chars:
                print(f"DEBUG: Found {len(problematic_chars)} non-ASCII characters")
                for pos, char, code in problematic_chars[:10]:  # Показываем первые 10
                    print(f"  Position {pos}: '{char}' (code: {code})")

            # Подготавливаем данные БЕЗ Markdown для тестирования
            data = {
                "chat_id": chat_id,
                "text": message,
                # "parse_mode": "Markdown",  # Временно отключаем
                "disable_web_page_preview": True,
            }

            print(f"DEBUG: Request data keys: {list(data.keys())}")
            print(f"DEBUG: Parse mode: {data['parse_mode']}")

            # Кодируем данные
            encoded_data = urlencode(data).encode("utf-8")
            print(f"DEBUG: Encoded data length: {len(encoded_data)}")

            # Создаем запрос
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            request = Request(
                api_url,
                data=encoded_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            print(f"DEBUG: API URL: {api_url[:50]}...")
            print(f"DEBUG: Request headers: {request.headers}")

            # Отправляем запрос
            try:
                with urlopen(request, timeout=10) as response:
                    response_data = response.read().decode("utf-8")
                    print(f"DEBUG: Response status: {response.status}")
                    print(f"DEBUG: Response data: {response_data}")

                    result = json.loads(response_data)

                    if result.get("ok"):
                        print("DEBUG: Message sent successfully!")
                        return True
                    else:
                        print(f"DEBUG: Telegram API returned error: {result}")
                        logger.error(f"Telegram API error: {result}")
                        return False

            except HTTPError as e:
                print(f"DEBUG: HTTP Error {e.code}: {e.reason}")
                if hasattr(e, "read"):
                    error_body = e.read().decode("utf-8")
                    print(f"DEBUG: Error response body: {error_body}")
                    try:
                        error_json = json.loads(error_body)
                        print(f"DEBUG: Parsed error JSON: {error_json}")
                    except:
                        pass
                raise e

        except Exception as e:
            print(
                f"DEBUG: Exception in _send_telegram_message: {type(e).__name__}: {e}"
            )
            logger.error(f"Error sending telegram message: {e}")
            return False
