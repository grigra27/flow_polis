"""
Django management команда для отправки ежедневного дайджеста в Telegram
"""
import logging
from datetime import datetime, timedelta, date
from django.utils import timezone
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.db import models
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
            payments_data = self._get_payments_data(start_time, end_time)

            # Формируем сообщение
            message = self._format_message(
                period_name, logins_data, policies_data, payments_data
            )

            # Отправляем в Telegram (разделяем на части если нужно)
            full_message = f"📊 Дайджест за {period_name}\n\n{message}"

            # Разделяем на части если сообщение слишком длинное
            message_parts = self._split_message_into_parts(full_message)

            print(f"DEBUG: Message split into {len(message_parts)} parts")
            for i, part in enumerate(message_parts):
                print(f"DEBUG: Part {i+1} length: {len(part)}")

            success = self._send_telegram_messages(message_parts)

            if success:
                if len(message_parts) > 1:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✅ Дайджест отправлен в Telegram ({len(message_parts)} частей)"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS("✅ Дайджест отправлен в Telegram")
                    )
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️ Не удалось отправить дайджест в Telegram")
                )

        except Exception as e:
            logger.exception(f"Ошибка при генерации дайджеста: {e}")
            self.stdout.write(self.style.ERROR(f"❌ Ошибка: {e}"))

    def _analyze_payment_changes(self, changes):
        """Анализирует изменения платежа и возвращает важные изменения"""
        import json

        # Поля которые считаем важными для отображения в платежах
        important_fields = {
            "paid_date": {
                "name": "Дата оплаты",
                "emoji": "✅",
                "format": "date_payment",
            },
            "insurer_date": {
                "name": "Согласование СК",
                "emoji": "📋",
                "format": "date_payment",
            },
            "amount": {"name": "Сумма платежа", "emoji": "💰", "format": "money"},
            "kv_rub": {"name": "КВ", "emoji": "🤝", "format": "money"},
            "due_date": {"name": "Дата по договору", "emoji": "📅", "format": "date"},
            "insurance_sum": {
                "name": "Страховая сумма",
                "emoji": "🏦",
                "format": "money",
            },
        }

        important_changes = []

        for change in changes:
            if (
                change["change"].action == LogEntry.Action.UPDATE
                and change["change"].changes
            ):
                try:
                    # Парсим JSON с изменениями
                    changes_data = change["change"].changes
                    if isinstance(changes_data, str):
                        changes_dict = json.loads(changes_data)
                    else:
                        changes_dict = changes_data

                    for field_name, (old_value, new_value) in changes_dict.items():
                        if field_name in important_fields:
                            field_info = important_fields[field_name]

                            # Форматируем значения
                            formatted_change = self._format_payment_field_change(
                                field_info, old_value, new_value
                            )

                            if formatted_change:
                                important_changes.append(formatted_change)

                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    # Если не удалось распарсить изменения, пропускаем
                    continue

        return important_changes

    def _format_payment_field_change(self, field_info, old_value, new_value):
        """Форматирует изменение поля платежа для отображения"""
        from decimal import Decimal

        if old_value == new_value:
            return None

        emoji = field_info["emoji"]
        name = field_info["name"]
        format_type = field_info["format"]

        if format_type == "date_payment":
            # Специальная обработка для дат платежей
            if old_value in [None, "None", ""] and new_value not in [None, "None", ""]:
                # Дата была добавлена
                return f"{emoji} {name}: {new_value}"
            elif old_value not in [None, "None", ""] and new_value in [
                None,
                "None",
                "",
            ]:
                # Дата была удалена
                return f"{emoji} {name}: удалена ({old_value})"
            elif old_value not in [None, "None", ""] and new_value not in [
                None,
                "None",
                "",
            ]:
                # Дата была изменена
                return f"{emoji} {name}: {old_value} → {new_value}"
            else:
                return None

        elif format_type == "money":
            try:
                old_val = Decimal(str(old_value)) if old_value else Decimal("0")
                new_val = Decimal(str(new_value)) if new_value else Decimal("0")

                # Показываем изменение
                diff = new_val - old_val
                if diff > 0:
                    return f"{emoji} {name}: +{diff:,.0f}₽ ({old_val:,.0f}₽ → {new_val:,.0f}₽)"
                elif diff < 0:
                    return f"{emoji} {name}: {diff:,.0f}₽ ({old_val:,.0f}₽ → {new_val:,.0f}₽)"
                else:
                    return None
            except (ValueError, TypeError):
                return f"{emoji} {name}: {old_value} → {new_value}"

        elif format_type == "date":
            return f"{emoji} {name}: {old_value} → {new_value}"

        else:  # text
            return f"{emoji} {name}: {old_value} → {new_value}"

    def _analyze_policy_changes(self, changes):
        """Анализирует изменения полиса и возвращает важные изменения"""
        import json

        # Поля которые считаем важными для отображения
        important_fields = {
            "premium_total": {"name": "Премия", "emoji": "💰", "format": "money"},
            "start_date": {"name": "Дата начала", "emoji": "📅", "format": "date"},
            "end_date": {"name": "Дата окончания", "emoji": "📅", "format": "date"},
            "franchise": {"name": "Франшиза", "emoji": "🛡️", "format": "money"},
            "policy_active": {
                "name": "Статус полиса",
                "emoji": "🔄",
                "format": "boolean",
            },
            "dfa_active": {"name": "Статус ДФА", "emoji": "📋", "format": "boolean"},
            "client": {"name": "Клиент", "emoji": "👤", "format": "text"},
            "insurer": {"name": "Страховщик", "emoji": "🏢", "format": "text"},
        }

        important_changes = []

        for change in changes:
            if change.action == LogEntry.Action.UPDATE and change.changes:
                try:
                    # Парсим JSON с изменениями
                    if isinstance(change.changes, str):
                        changes_dict = json.loads(change.changes)
                    else:
                        changes_dict = change.changes

                    for field_name, (old_value, new_value) in changes_dict.items():
                        if field_name in important_fields:
                            field_info = important_fields[field_name]

                            # Форматируем значения
                            formatted_change = self._format_field_change(
                                field_info, old_value, new_value
                            )

                            if formatted_change:
                                important_changes.append(formatted_change)

                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    # Если не удалось распарсить изменения, пропускаем
                    continue

        return important_changes

    def _format_field_change(self, field_info, old_value, new_value):
        """Форматирует изменение поля для отображения"""
        from decimal import Decimal

        if old_value == new_value:
            return None

        emoji = field_info["emoji"]
        name = field_info["name"]
        format_type = field_info["format"]

        if format_type == "money":
            try:
                old_val = Decimal(str(old_value)) if old_value else Decimal("0")
                new_val = Decimal(str(new_value)) if new_value else Decimal("0")

                # Показываем изменение
                diff = new_val - old_val
                if diff > 0:
                    return f"{emoji} {name}: +{diff:,.0f}₽ ({old_val:,.0f}₽ → {new_val:,.0f}₽)"
                elif diff < 0:
                    return f"{emoji} {name}: {diff:,.0f}₽ ({old_val:,.0f}₽ → {new_val:,.0f}₽)"
                else:
                    return None
            except (ValueError, TypeError):
                return f"{emoji} {name}: {old_value} → {new_value}"

        elif format_type == "date":
            return f"{emoji} {name}: {old_value} → {new_value}"

        elif format_type == "boolean":
            old_status = "Активен" if old_value else "Неактивен"
            new_status = "Активен" if new_value else "Неактивен"
            return f"{emoji} {name}: {old_status} → {new_status}"

        else:  # text
            return f"{emoji} {name}: {old_value} → {new_value}"

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

    def _escape_html_text(self, text):
        """Экранирует специальные символы для HTML"""
        if not text:
            return text

        # Экранируем HTML символы
        result = str(text)
        result = result.replace("&", "&amp;")
        result = result.replace("<", "&lt;")
        result = result.replace(">", "&gt;")
        result = result.replace('"', "&quot;")
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
        """Получает данные об изменениях полисов с расширенной статистикой"""
        from decimal import Decimal

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
        policies_data = {
            "created": [],
            "updated": [],
            "payment_changes": [],
            "statistics": {
                "total_created": 0,
                "total_updated": 0,
                "total_payment_changes": 0,
                "premium_sum_created": Decimal("0"),
                "kv_sum_created": Decimal("0"),
                "premium_sum_payments": Decimal("0"),
                "kv_sum_payments": Decimal("0"),
            },
        }

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

                # Анализируем изменения для умного отображения
                change_details = self._analyze_policy_changes(changes)

                policy_info = {
                    "policy": policy,
                    "url": f"https://polis.insflow.ru/policies/{policy.pk}/",
                    "changes": changes,
                    "change_details": change_details,
                }

                if has_create:
                    policies_data["created"].append(policy_info)
                    policies_data["statistics"]["total_created"] += 1

                    # Добавляем премию и КВ для новых полисов
                    if policy.premium_total:
                        policies_data["statistics"][
                            "premium_sum_created"
                        ] += policy.premium_total

                    # Считаем КВ по всем платежам нового полиса
                    kv_sum = policy.payment_schedule.aggregate(
                        total_kv=models.Sum("kv_rub")
                    )["total_kv"] or Decimal("0")
                    policies_data["statistics"]["kv_sum_created"] += kv_sum

                elif has_update:
                    policies_data["updated"].append(policy_info)
                    policies_data["statistics"]["total_updated"] += 1

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

                # Добавляем статистику по платежам
                if change.action == LogEntry.Action.CREATE:
                    policies_data["statistics"][
                        "premium_sum_payments"
                    ] += payment.amount
                    policies_data["statistics"]["kv_sum_payments"] += payment.kv_rub

            except PaymentSchedule.DoesNotExist:
                continue

        # Добавляем изменения платежей (только если сам полис не менялся)
        for policy_id, payment_data in payment_changes_by_policy.items():
            if str(policy_id) not in policy_changes_by_id:  # Полис сам не менялся
                payment_data["url"] = f"https://polis.insflow.ru/policies/{policy_id}/"

                # Анализируем изменения платежей (новое!)
                payment_data["change_details"] = self._analyze_payment_changes(
                    payment_data["changes"]
                )

                policies_data["payment_changes"].append(payment_data)
                policies_data["statistics"]["total_payment_changes"] += 1

        return policies_data

    def _get_payments_data(self, start_time, end_time):
        """Получает данные о платежах за период"""
        from decimal import Decimal
        from datetime import date

        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Платежи которые должны были быть оплачены в этот период
        due_payments = PaymentSchedule.objects.filter(
            due_date__gte=start_time.date(), due_date__lt=end_time.date()
        ).select_related("policy__client", "policy__insurer")

        # Платежи которые были фактически оплачены в этот период
        paid_payments = PaymentSchedule.objects.filter(
            paid_date__gte=start_time.date(), paid_date__lt=end_time.date()
        ).select_related("policy__client", "policy__insurer")

        # Просроченные платежи (должны были быть оплачены до сегодня, но не оплачены)
        overdue_payments = PaymentSchedule.objects.filter(
            due_date__lt=today,
            paid_date__isnull=True,
            policy__policy_active=True,  # Только по активным полисам
        ).select_related("policy__client", "policy__insurer")

        # Платежи на завтра
        tomorrow_payments = PaymentSchedule.objects.filter(
            due_date=tomorrow, paid_date__isnull=True, policy__policy_active=True
        ).select_related("policy__client", "policy__insurer")

        # Считаем суммы
        paid_sum = paid_payments.aggregate(total=models.Sum("amount"))[
            "total"
        ] or Decimal("0")
        paid_kv_sum = paid_payments.aggregate(total=models.Sum("kv_rub"))[
            "total"
        ] or Decimal("0")

        overdue_sum = overdue_payments.aggregate(total=models.Sum("amount"))[
            "total"
        ] or Decimal("0")
        tomorrow_sum = tomorrow_payments.aggregate(total=models.Sum("amount"))[
            "total"
        ] or Decimal("0")

        return {
            "due_payments": list(due_payments),
            "paid_payments": list(paid_payments),
            "overdue_payments": list(overdue_payments),
            "tomorrow_payments": list(tomorrow_payments),
            "statistics": {
                "due_count": due_payments.count(),
                "paid_count": paid_payments.count(),
                "paid_sum": paid_sum,
                "paid_kv_sum": paid_kv_sum,
                "overdue_count": overdue_payments.count(),
                "overdue_sum": overdue_sum,
                "tomorrow_count": tomorrow_payments.count(),
                "tomorrow_sum": tomorrow_sum,
            },
        }

    def _format_message(self, period_name, logins_data, policies_data, payments_data):
        """Форматирует сообщение для отправки с расширенной статистикой и улучшенным форматированием"""
        print(f"DEBUG: Formatting message for period: {period_name}")
        print(f"DEBUG: Logins count: {len(logins_data)}")
        print(f"DEBUG: Policies created: {len(policies_data['created'])}")
        print(f"DEBUG: Policies updated: {len(policies_data['updated'])}")
        print(f"DEBUG: Payment changes: {len(policies_data['payment_changes'])}")

        message_parts = []
        stats = policies_data["statistics"]
        payment_stats = payments_data["statistics"]

        # 📊 СВОДНАЯ СТАТИСТИКА (новое!)
        message_parts.append("📊 СВОДНАЯ СТАТИСТИКА:")

        # Общие цифры по полисам
        total_policies = stats["total_created"] + stats["total_updated"]
        message_parts.append(
            f"📋 Всего полисов: {total_policies} (создано: {stats['total_created']}, изменено: {stats['total_updated']})"
        )

        if stats["total_payment_changes"] > 0:
            message_parts.append(
                f"💳 Изменений платежей: {stats['total_payment_changes']}"
            )

        # Суммы по новым полисам
        if stats["premium_sum_created"] > 0:
            message_parts.append(
                f"💰 Премии по новым полисам: {stats['premium_sum_created']:,.0f}₽"
            )

        if stats["kv_sum_created"] > 0:
            message_parts.append(
                f"🤝 КВ по новым полисам: {stats['kv_sum_created']:,.0f}₽"
            )

        # Суммы по новым платежам
        if stats["premium_sum_payments"] > 0:
            message_parts.append(
                f"💸 Премии по новым платежам: {stats['premium_sum_payments']:,.0f}₽"
            )

        if stats["kv_sum_payments"] > 0:
            message_parts.append(
                f"💼 КВ по новым платежам: {stats['kv_sum_payments']:,.0f}₽"
            )

        # Статистика по платежам (новое!)
        if payment_stats["paid_count"] > 0:
            message_parts.append(
                f"✅ Оплачено платежей: {payment_stats['paid_count']} на сумму {payment_stats['paid_sum']:,.0f}₽"
            )
            if payment_stats["paid_kv_sum"] > 0:
                message_parts.append(
                    f"💼 КВ с оплаченных: {payment_stats['paid_kv_sum']:,.0f}₽"
                )

        # Предупреждения о просрочке и завтрашних платежах
        if payment_stats["overdue_count"] > 0:
            message_parts.append(
                f"⚠️ Просрочено: {payment_stats['overdue_count']} платежей на {payment_stats['overdue_sum']:,.0f}₽"
            )

        if payment_stats["tomorrow_count"] > 0:
            message_parts.append(
                f"📅 Завтра к оплате: {payment_stats['tomorrow_count']} платежей на {payment_stats['tomorrow_sum']:,.0f}₽"
            )

        # Если никакой активности не было
        if (
            total_policies == 0
            and stats["total_payment_changes"] == 0
            and payment_stats["paid_count"] == 0
        ):
            message_parts.append("📭 Активности не было")

        message_parts.append("")  # Разделитель

        # 👥 ЛОГИНЫ ПОЛЬЗОВАТЕЛЕЙ (улучшенное форматирование)
        message_parts.append("👥 АКТИВНОСТЬ ПОЛЬЗОВАТЕЛЕЙ:")
        if logins_data:
            # Группируем логины по пользователям
            user_logins = {}
            for login in logins_data:
                username = login["username"]
                if username not in user_logins:
                    user_logins[username] = []
                user_logins[username].append(login["time"])

            # Показываем сгруппированно
            for username, times in user_logins.items():
                if len(times) == 1:
                    message_parts.append(f"• {times[0]} - {username}")
                else:
                    times_str = ", ".join(times)
                    message_parts.append(
                        f"• {username}: {times_str} ({len(times)} входов)"
                    )
        else:
            message_parts.append("• Входов не было")

        message_parts.append("")  # Разделитель

        # 💰 ИНФОРМАЦИЯ О ПЛАТЕЖАХ (новое!)
        if (
            payment_stats["paid_count"] > 0
            or payment_stats["overdue_count"] > 0
            or payment_stats["tomorrow_count"] > 0
        ):
            message_parts.append("💰 ДЕТАЛИ ПО ПЛАТЕЖАМ:")

            # Оплаченные платежи
            if payment_stats["paid_count"] > 0:
                message_parts.append("")
                message_parts.append("✅ ОПЛАЧЕНО:")
                # Показываем только первые 5 оплаченных платежей, чтобы не перегружать
                for payment in payments_data["paid_payments"][:5]:
                    policy_number = (
                        payment.policy.dfa_number
                        or payment.policy.policy_number
                        or f"Policy-{payment.policy.pk}"
                    )
                    client_name = (
                        payment.policy.client.client_name or "Неизвестный клиент"
                    )
                    message_parts.append(
                        f"• {policy_number} | {client_name} | {payment.amount:,.0f}₽"
                    )

                if len(payments_data["paid_payments"]) > 5:
                    remaining = len(payments_data["paid_payments"]) - 5
                    message_parts.append(f"• ... и еще {remaining} платежей")

            # Просроченные платежи (показываем только если их немного)
            if (
                payment_stats["overdue_count"] > 0
                and payment_stats["overdue_count"] <= 10
            ):
                message_parts.append("")
                message_parts.append("⚠️ ПРОСРОЧЕНО:")
                for payment in payments_data["overdue_payments"]:
                    policy_number = (
                        payment.policy.dfa_number
                        or payment.policy.policy_number
                        or f"Policy-{payment.policy.pk}"
                    )
                    client_name = (
                        payment.policy.client.client_name or "Неизвестный клиент"
                    )
                    days_overdue = (date.today() - payment.due_date).days
                    message_parts.append(
                        f"• {policy_number} | {client_name} | {payment.amount:,.0f}₽ ({days_overdue} дн.)"
                    )
            elif payment_stats["overdue_count"] > 10:
                message_parts.append("")
                message_parts.append(
                    f"⚠️ ПРОСРОЧЕНО: {payment_stats['overdue_count']} платежей (слишком много для детального отображения)"
                )

            # Завтрашние платежи (показываем только если их немного)
            if (
                payment_stats["tomorrow_count"] > 0
                and payment_stats["tomorrow_count"] <= 10
            ):
                message_parts.append("")
                message_parts.append("📅 ЗАВТРА К ОПЛАТЕ:")
                for payment in payments_data["tomorrow_payments"]:
                    policy_number = (
                        payment.policy.dfa_number
                        or payment.policy.policy_number
                        or f"Policy-{payment.policy.pk}"
                    )
                    client_name = (
                        payment.policy.client.client_name or "Неизвестный клиент"
                    )
                    message_parts.append(
                        f"• {policy_number} | {client_name} | {payment.amount:,.0f}₽"
                    )
            elif payment_stats["tomorrow_count"] > 10:
                message_parts.append("")
                message_parts.append(
                    f"📅 ЗАВТРА К ОПЛАТЕ: {payment_stats['tomorrow_count']} платежей (слишком много для детального отображения)"
                )

            message_parts.append("")  # Разделитель

        # 📋 ДЕТАЛЬНАЯ ИНФОРМАЦИЯ ПО ПОЛИСАМ
        message_parts.append("📋 ДЕТАЛИ ПО ПОЛИСАМ:")

        # Созданные полисы (улучшенное форматирование)
        if policies_data["created"]:
            message_parts.append("")
            message_parts.append("🆕 СОЗДАНЫ:")
            for i, item in enumerate(policies_data["created"]):
                policy = item["policy"]
                print(f"DEBUG: Processing created policy {i+1}: ID={policy.pk}")

                # Используем номер ДФА если есть, иначе номер полиса
                policy_number = (
                    policy.dfa_number if policy.dfa_number else policy.policy_number
                )
                policy_number = policy_number or f"Policy-{policy.pk}"
                client_name = policy.client.client_name or "Неизвестный клиент"
                insurer_name = policy.insurer.insurer_name or "Неизвестная страховая"

                # Основная информация
                line = f"• {policy_number} | {client_name} | {insurer_name}"
                message_parts.append(line)

                # Дополнительная информация о новом полисе
                if policy.premium_total:
                    message_parts.append(f"  💰 Премия: {policy.premium_total:,.0f}₽")

                # КВ по полису
                kv_sum = policy.payment_schedule.aggregate(
                    total_kv=models.Sum("kv_rub")
                )["total_kv"]
                if kv_sum:
                    message_parts.append(f"  🤝 КВ: {kv_sum:,.0f}₽")

                message_parts.append(f"  🔗 {item['url']}")

        # Обновленные полисы (с расширенной детализацией изменений!)
        if policies_data["updated"]:
            message_parts.append("")
            message_parts.append("✏️ ИЗМЕНЕНЫ:")
            for i, item in enumerate(policies_data["updated"]):
                policy = item["policy"]
                print(f"DEBUG: Processing updated policy {i+1}: ID={policy.pk}")

                policy_number = (
                    policy.dfa_number if policy.dfa_number else policy.policy_number
                )
                policy_number = policy_number or f"Policy-{policy.pk}"
                client_name = policy.client.client_name or "Неизвестный клиент"
                insurer_name = policy.insurer.insurer_name or "Неизвестная страховая"

                # Основная информация
                line = f"• {policy_number} | {client_name} | {insurer_name}"
                message_parts.append(line)

                # Показываем расширенную детализацию изменений
                if item.get("change_details"):
                    # Добавляем счетчик изменений
                    changes_count = len(item["change_details"])
                    message_parts.append(f"  📝 Изменений: {changes_count}")

                    # Показываем каждое изменение с отступом
                    for change_detail in item["change_details"]:
                        message_parts.append(f"  {change_detail}")
                else:
                    # Если нет детальной информации, показываем общее количество изменений
                    changes_count = len(item["changes"])
                    message_parts.append(f"  📝 Изменений: {changes_count}")

                message_parts.append(f"  🔗 {item['url']}")

        # Изменения платежей (улучшенное форматирование с расширенной детализацией)
        if policies_data["payment_changes"]:
            message_parts.append("")
            message_parts.append("💳 ИЗМЕНЕНЫ ПЛАТЕЖИ:")
            for i, item in enumerate(policies_data["payment_changes"]):
                policy = item["policy"]
                print(f"DEBUG: Processing payment change {i+1}: ID={policy.pk}")

                policy_number = (
                    policy.dfa_number if policy.dfa_number else policy.policy_number
                )
                policy_number = policy_number or f"Policy-{policy.pk}"
                client_name = policy.client.client_name or "Неизвестный клиент"
                insurer_name = policy.insurer.insurer_name or "Неизвестная страховая"

                line = f"• {policy_number} | {client_name} | {insurer_name}"
                message_parts.append(line)

                # Показываем расширенную детализацию изменений платежей
                if item.get("change_details"):
                    # Добавляем счетчик изменений платежей
                    changes_count = len(item["change_details"])
                    message_parts.append(f"  📝 Изменений платежей: {changes_count}")

                    # Показываем каждое изменение с отступом
                    for change_detail in item["change_details"]:
                        message_parts.append(f"  {change_detail}")
                else:
                    # Если нет детальной информации, показываем количество изменений
                    changes_count = len(item["changes"])
                    created_count = sum(
                        1
                        for change in item["changes"]
                        if change["change"].action == LogEntry.Action.CREATE
                    )
                    updated_count = changes_count - created_count

                    if created_count > 0 and updated_count > 0:
                        message_parts.append(
                            f"  📝 Изменений: {changes_count} (создано: {created_count}, изменено: {updated_count})"
                        )
                    elif created_count > 0:
                        message_parts.append(f"  📝 Создано платежей: {created_count}")
                    else:
                        message_parts.append(f"  📝 Изменено платежей: {updated_count}")

                message_parts.append(f"  🔗 {item['url']}")

        # Если никаких изменений полисов не было
        if not any(
            [
                policies_data["created"],
                policies_data["updated"],
                policies_data["payment_changes"],
            ]
        ):
            message_parts.append("📭 Изменений полисов не было")

        final_message = "\n".join(message_parts)
        print(f"DEBUG: Final message length: {len(final_message)}")
        print(f"DEBUG: Final message preview: {repr(final_message[:300])}")

        return final_message

    def _truncate_message(self, message, max_length):
        """Сокращает сообщение до указанной длины, сохраняя важную информацию"""
        if len(message) <= max_length:
            return message

        lines = message.split("\n")
        result_lines = []
        current_length = 0

        # Резервируем место для информации о сокращении
        truncate_info = "... (сообщение сокращено из-за лимита Telegram)"
        reserve_length = len(truncate_info) + 10  # +10 для безопасности
        effective_max_length = max_length - reserve_length

        # Всегда включаем сводную статистику (первые строки)
        for i, line in enumerate(lines):
            line_length = len(line)

            # Проверяем, поместится ли строка
            if current_length + line_length + 1 > effective_max_length:
                # Добавляем информацию о сокращении
                remaining_lines = len(lines) - i
                if remaining_lines > 0:
                    result_lines.append(
                        f"... и еще {remaining_lines} строк {truncate_info}"
                    )
                break

            result_lines.append(line)
            current_length += line_length + 1  # +1 для \n

            # Прерываем после сводной статистики и активности пользователей если места мало
            if (
                line.startswith("📋 ДЕТАЛИ ПО ПОЛИСАМ:")
                and current_length > effective_max_length * 0.6
            ):  # Если уже использовано 60% места
                remaining_lines = len(lines) - i - 1
                if remaining_lines > 0:
                    result_lines.append(
                        f"... детали по {remaining_lines} элементам {truncate_info}"
                    )
                break

        result = "\n".join(result_lines)

        # Финальная проверка длины и принудительное сокращение если нужно
        if len(result) > max_length:
            # Принудительно сокращаем до нужной длины
            result = result[: max_length - len(truncate_info)] + truncate_info

        return result

    def _split_message_into_parts(self, message, max_length=3900):
        """Разделяет длинное сообщение на несколько частей по логическим разделам"""
        if len(message) <= max_length:
            return [message]

        lines = message.split("\n")
        parts = []
        current_part = []
        current_length = 0

        # Определяем разделители секций
        section_headers = [
            "📊 СВОДНАЯ СТАТИСТИКА:",
            "👥 АКТИВНОСТЬ ПОЛЬЗОВАТЕЛЕЙ:",
            "💰 ДЕТАЛИ ПО ПЛАТЕЖАМ:",
            "📋 ДЕТАЛИ ПО ПОЛИСАМ:",
            "🆕 СОЗДАНЫ:",
            "✏️ ИЗМЕНЕНЫ:",
            "💳 ИЗМЕНЕНЫ ПЛАТЕЖИ:",
        ]

        for i, line in enumerate(lines):
            line_length = len(line)

            # Проверяем, является ли строка заголовком новой секции
            is_section_header = any(
                line.startswith(header) for header in section_headers
            )

            # Если добавление строки превысит лимит и у нас уже есть контент
            if current_length + line_length + 1 > max_length and current_part:
                # Сохраняем текущую часть
                if current_part:
                    parts.append("\n".join(current_part))

                # Начинаем новую часть
                current_part = [line]
                current_length = line_length
            else:
                # Добавляем строку к текущей части
                current_part.append(line)
                current_length += line_length + 1  # +1 для \n

        # Добавляем последнюю часть
        if current_part:
            parts.append("\n".join(current_part))

        return parts

    def _send_telegram_messages(self, messages):
        """Отправляет несколько сообщений в Telegram с задержкой между ними"""
        import time

        success_count = 0
        total_messages = len(messages)

        for i, message in enumerate(messages):
            print(
                f"DEBUG: Sending message {i+1}/{total_messages} (length: {len(message)})"
            )

            # Добавляем номер части если сообщений больше одного
            if total_messages > 1:
                if i == 0:
                    message = f"{message}\n\n📄 Часть 1/{total_messages}"
                else:
                    message = f"📄 Часть {i+1}/{total_messages}\n\n{message}"

            success = self._send_single_telegram_message(message)

            if success:
                success_count += 1
                print(f"DEBUG: Message {i+1}/{total_messages} sent successfully")

                # Задержка между сообщениями (кроме последнего)
                if i < total_messages - 1:
                    time.sleep(1)  # 1 секунда между сообщениями
            else:
                print(f"ERROR: Failed to send message {i+1}/{total_messages}")
                # Продолжаем отправку остальных сообщений

        print(f"DEBUG: Successfully sent {success_count}/{total_messages} messages")
        return (
            success_count > 0
        )  # Возвращаем True если хотя бы одно сообщение отправлено

    def _send_single_telegram_message(self, message):
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

            # Проверяем длину сообщения и сокращаем если нужно
            MAX_MESSAGE_LENGTH = (
                3900  # Консервативный лимит с запасом для заголовка и кодировки
            )

            if len(message) > MAX_MESSAGE_LENGTH:
                print(
                    f"DEBUG: Message too long ({len(message)} chars), truncating to {MAX_MESSAGE_LENGTH}..."
                )
                message = self._truncate_message(message, MAX_MESSAGE_LENGTH)
                print(f"DEBUG: Truncated message length: {len(message)}")
                print(
                    f"DEBUG: Truncated message preview: {repr(message[-200:])}"
                )  # Показываем конец

            # Подготавливаем данные БЕЗ parse_mode (как в остальном проекте)
            data = {
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            }

            print(f"DEBUG: Request data keys: {list(data.keys())}")
            if "parse_mode" in data:
                print(f"DEBUG: Parse mode: {data['parse_mode']}")
            else:
                print(
                    f"DEBUG: No parse mode (plain text) - совместимо с остальным проектом"
                )

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
