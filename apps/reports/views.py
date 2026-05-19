from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, FormView, View
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, FileResponse
from django.conf import settings
from django.utils import timezone
from django.db import DatabaseError
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from apps.policies.models import Policy, PaymentSchedule
from apps.insurers.models import Insurer
from .models import CustomExportTemplate
from .forms import CustomExportForm
from .filters import (
    PolicyExportFilter,
    PaymentExportFilter,
)
from .exporters import CustomExporter, PolicyExporter
import logging

logger = logging.getLogger(__name__)


def _is_admin_user(user):
    return user.is_staff or user.is_superuser


def _format_file_size(size_bytes):
    """Форматирует размер файла в человекочитаемый вид."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(size_bytes)} B"


def _is_path_within_directory(path, directory):
    """Проверяет, что path находится внутри directory (защита от path traversal)."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False
    except FileNotFoundError:
        return False


def _get_backup_search_dirs(backup_type):
    """
    Возвращает список директорий для поиска backup-файлов.
    Поддерживает как docker/mount сценарий, так и локальный запуск без контейнера.
    """
    subdir = "database" if backup_type == "database" else "media"
    explicit_dir = (
        settings.BACKUP_DB_DIR
        if backup_type == "database"
        else settings.BACKUP_MEDIA_DIR
    )

    candidates = []

    if explicit_dir:
        candidates.append(Path(explicit_dir))

    if settings.BACKUP_BASE_DIR:
        base_path = Path(settings.BACKUP_BASE_DIR)
        candidates.append(base_path / subdir)
        candidates.append(base_path)

    candidates.extend(
        [
            Path("/app/server_backups") / subdir,
            Path("/app/server_backups"),
            Path("/app/backups") / subdir,
            Path("/app/backups"),
            Path.home() / "insurance_broker_backups" / subdir,
            Path(settings.BASE_DIR) / "backups" / subdir,
            Path(settings.BASE_DIR) / "backups",
        ]
    )

    unique_dirs = []
    seen = set()
    for candidate in candidates:
        normalized = str(candidate.expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_dirs.append(candidate.expanduser())

    return unique_dirs


def _find_latest_backup_file(backup_type):
    """Находит актуальный backup-файл по типу (database/media)."""
    latest_filename = (
        "latest_backup.sql.gz" if backup_type == "database" else "latest_backup.tar.gz"
    )
    fallback_patterns = (
        ["db_backup_*.sql.gz", "*.sql.gz"]
        if backup_type == "database"
        else ["media_backup_*.tar.gz", "*.tar.gz"]
    )

    for backup_dir in _get_backup_search_dirs(backup_type):
        try:
            if not backup_dir.exists() or not backup_dir.is_dir():
                continue
        except OSError:
            continue

        latest_file = backup_dir / latest_filename
        if latest_file.exists() and latest_file.is_file():
            try:
                resolved_latest = latest_file.resolve()
                if _is_path_within_directory(resolved_latest, backup_dir):
                    return resolved_latest
            except OSError:
                pass

        for pattern in fallback_patterns:
            try:
                matches = sorted(
                    [p for p in backup_dir.glob(pattern) if p.is_file()],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                continue

            if matches:
                try:
                    resolved_match = matches[0].resolve()
                    if _is_path_within_directory(resolved_match, backup_dir):
                        return resolved_match
                except OSError:
                    continue

    return None


def _get_backup_file_info(backup_type):
    """Возвращает информацию о найденном backup-файле для отображения в UI."""
    backup_file = _find_latest_backup_file(backup_type)
    if not backup_file:
        return {
            "available": False,
            "filename": None,
            "size": None,
            "modified_at": None,
        }

    try:
        stat = backup_file.stat()
    except OSError:
        return {
            "available": False,
            "filename": None,
            "size": None,
            "modified_at": None,
        }

    modified_at = timezone.localtime(
        datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc)
    )

    return {
        "available": True,
        "filename": backup_file.name,
        "size": _format_file_size(stat.st_size),
        "modified_at": modified_at,
    }


def _download_backup_file(request, backup_type):
    """Общий обработчик скачивания backup-файлов."""
    if not _is_admin_user(request.user):
        messages.error(request, "У вас нет прав для выполнения этого действия")
        return redirect("reports:index")

    backup_file = _find_latest_backup_file(backup_type)
    if not backup_file:
        messages.error(
            request,
            "Актуальный backup-файл не найден. Проверьте настройки backup-директории.",
        )
        return redirect("reports:index")

    try:
        file_handle = open(backup_file, "rb")
    except OSError as exc:
        logger.error(f"Failed to open backup file {backup_file}: {exc}")
        messages.error(request, "Не удалось открыть backup-файл для скачивания")
        return redirect("reports:index")

    content_type = "application/gzip"
    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=backup_file.name,
        content_type=content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"

    logger.info(
        "User %s downloaded %s backup file: %s",
        request.user.username,
        backup_type,
        backup_file,
    )
    return response


@login_required
def reports_index(request):
    """Reports main page"""
    return render(request, "reports/index.html")


@login_required
def export_policies_excel(request):
    """Export policies to Excel"""
    try:
        # Получаем все полисы с оптимизированными запросами
        policies = Policy.objects.select_related(
            "client", "insurer", "branch", "insurance_type"
        ).all()

        # Применяем опциональные фильтры (если переданы)
        branch_id = request.GET.get("branch")
        if branch_id:
            policies = policies.filter(branch_id=branch_id)

        # Генерируем отчет
        exporter = PolicyExporter(policies, [])

        # Логируем
        logger.info(
            f"User {request.user.username} exported policies (count: {policies.count()})"
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting policies: {e}")
        messages.error(request, "Ошибка при создании экспорта полисов")
        return redirect("reports:index")


@login_required
def export_payments_excel(request):
    """Export payment schedule to Excel with date range filter"""
    try:
        # Получаем параметры дат из запроса
        date_from_str = request.GET.get("date_from")
        date_to_str = request.GET.get("date_to")

        # Проверяем наличие обязательных параметров
        if not date_from_str or not date_to_str:
            messages.error(
                request, "Необходимо указать дату начала и дату окончания периода"
            )
            return redirect("reports:index")

        # Парсим даты
        try:
            from datetime import datetime

            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
        except ValueError:
            messages.error(
                request, "Неверный формат даты. Используйте формат ГГГГ-ММ-ДД"
            )
            return redirect("reports:index")

        # Проверяем корректность диапазона
        if date_from > date_to:
            messages.error(request, "Дата начала не может быть позже даты окончания")
            return redirect("reports:index")

        # Получаем платежи с оптимизированными запросами и фильтрацией по диапазону дат
        # Добавляем аннотацию для подсчета количества платежей в году
        # Сортируем по дате платежа (самая ранняя дата вверху)
        from django.db.models import Count, Q, OuterRef, Subquery

        # Подзапрос для подсчета платежей в том же году того же полиса
        payments_in_year_subquery = (
            PaymentSchedule.objects.filter(
                policy=OuterRef("policy"), year_number=OuterRef("year_number")
            )
            .values("policy", "year_number")
            .annotate(count=Count("id"))
            .values("count")
        )

        payments = (
            PaymentSchedule.objects.select_related(
                "policy",
                "policy__client",
                "policy__insurer",
                "policy__leasing_manager",
                "commission_rate",
            )
            .annotate(payments_in_year=Subquery(payments_in_year_subquery))
            .filter(
                due_date__gte=date_from,
                due_date__lte=date_to,
                policy__policy_active=True,  # Только активные полисы, как на странице платежей
                paid_date__isnull=True,  # Исключаем все платежи с датой фактической оплаты
            )
            .exclude(year_number=1, installment_number=1)
            .order_by("due_date", "policy__policy_number")
        )

        # Применяем опциональные фильтры
        branch_id = request.GET.get("branch")
        if branch_id:
            payments = payments.filter(policy__branch_id=branch_id)

        # Проверяем наличие данных
        if not payments.exists():
            messages.warning(
                request,
                f"Нет платежей в указанном периоде с {date_from_str} по {date_to_str}",
            )
            return redirect("reports:index")

        # Генерируем отчет с использованием нового экспортера
        from .exporters import ScheduledPaymentsExporter

        exporter = ScheduledPaymentsExporter(
            payments, [], date_from=date_from, date_to=date_to
        )

        # Логируем
        logger.info(
            f"User {request.user.username} exported payments (count: {payments.count()}, period: {date_from_str} - {date_to_str})"
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting payments: {e}")
        messages.error(request, "Ошибка при создании экспорта платежей")
        return redirect("reports:index")


@login_required
def export_thursday_report(request):
    """Export Thursday report - policies without documents and unpaid payments, grouped by city"""
    try:
        # Получаем все полисы, которые НЕ подгружены
        policies = (
            Policy.objects.select_related(
                "client", "insurer", "branch", "insurance_type", "policyholder"
            )
            .filter(policy_uploaded=False)
            .order_by("branch__branch_name", "policy_number")
        )

        # Применяем опциональные фильтры (если переданы)
        branch_id = request.GET.get("branch")
        if branch_id:
            policies = policies.filter(branch_id=branch_id)

        # Получаем дату для фильтрации раздела 2 (платежи)
        payment_date_str = request.GET.get("payment_date")
        payment_date = None
        if payment_date_str:
            try:
                from datetime import datetime

                payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning(f"Invalid payment_date format: {payment_date_str}")
                payment_date = None

        # Если дата не указана, используем текущую дату
        if not payment_date:
            from django.utils import timezone

            payment_date = timezone.now().date()

        # Отсекаем полисы, чьё страхование ещё не началось на дату среза —
        # по ним требовать документы/оплату преждевременно.
        policies = policies.filter(start_date__lte=payment_date)

        # Генерируем отчет с использованием специального экспортера
        from .exporters import ThursdayReportExporter

        exporter = ThursdayReportExporter(policies, [], payment_date=payment_date)

        # Логируем
        logger.info(
            f"User {request.user.username} exported Thursday report (not uploaded policies count: {policies.count()}, payment_date: {payment_date})"
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting Thursday report: {e}")
        messages.error(request, "Ошибка при создании четвергового отчета")
        return redirect("reports:index")


@login_required
def export_policy_expiration(request):
    """Export policies with expiration date in specified range"""
    try:
        # Получаем параметры дат из запроса
        date_from_str = request.GET.get("date_from")
        date_to_str = request.GET.get("date_to")

        # Проверяем наличие обязательных параметров
        if not date_from_str or not date_to_str:
            messages.error(
                request, "Необходимо указать дату начала и дату окончания периода"
            )
            return redirect("reports:index")

        # Парсим даты
        try:
            from datetime import datetime

            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
        except ValueError:
            messages.error(
                request, "Неверный формат даты. Используйте формат ГГГГ-ММ-ДД"
            )
            return redirect("reports:index")

        # Проверяем корректность диапазона
        if date_from > date_to:
            messages.error(request, "Дата начала не может быть позже даты окончания")
            return redirect("reports:index")

        # Получаем активные полисы с окончанием страхования в заданном диапазоне.
        # Статус ДФА не фильтруем: такие строки нужны в отчете и подсвечиваются.
        # Сортируем по филиалу (алфавитно), затем по дате окончания
        policies = (
            Policy.objects.select_related(
                "client",
                "insurer",
                "branch",
                "insurance_type",
                "policyholder",
                "leasing_manager",
            )
            .filter(end_date__gte=date_from, end_date__lte=date_to, policy_active=True)
            .order_by("branch__branch_name", "end_date", "policy_number")
        )

        # Применяем опциональные фильтры
        branch_id = request.GET.get("branch")
        if branch_id:
            policies = policies.filter(branch_id=branch_id)

        # Проверяем наличие данных
        if not policies.exists():
            messages.warning(
                request,
                f"Нет полисов с окончанием страхования в периоде с {date_from_str} по {date_to_str}",
            )
            return redirect("reports:index")

        # Генерируем отчет
        from .exporters import PolicyExpirationExporter

        exporter = PolicyExpirationExporter(
            policies, [], date_from=date_from, date_to=date_to
        )

        # Логируем
        logger.info(
            f"User {request.user.username} exported policy expiration report (count: {policies.count()}, period: {date_from_str} - {date_to_str})"
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting policy expiration report: {e}")
        messages.error(request, "Ошибка при создании экспорта полисов")
        return redirect("reports:index")


@login_required
def export_policies_csv(request):
    """Export payments to CSV format by date range"""
    # Проверяем права администратора
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "У вас нет прав для выполнения этого действия")
        return redirect("reports:index")

    try:
        import csv
        from django.utils import timezone
        from datetime import datetime

        # Получаем параметры периода из запроса
        start_date_param = request.GET.get("start_date")
        end_date_param = request.GET.get("end_date")

        # Проверяем наличие обязательных параметров
        if not start_date_param or not end_date_param:
            messages.error(
                request, "Необходимо указать дату начала и дату окончания периода"
            )
            return redirect("reports:index")

        # Парсим даты
        try:
            start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Неверный формат даты")
            return redirect("reports:index")

        # Проверяем корректность периода
        if start_date > end_date:
            messages.error(request, "Дата начала не может быть больше даты окончания")
            return redirect("reports:index")

        # Получаем платежи с оптимизированными запросами
        from django.db.models import F, Q

        # SQL-аналог PaymentSchedule.is_cancelled:
        # платёж не оплачен, полис расторгнут, и (даты расторжения нет
        # или дата платежа после расторжения).
        cancelled_filter = (
            Q(paid_date__isnull=True)
            & Q(policy__policy_active=False)
            & (
                Q(policy__termination_date__isnull=True)
                | Q(due_date__gt=F("policy__termination_date"))
            )
        )

        payments = (
            PaymentSchedule.objects.select_related(
                "policy__client",
                "policy__insurer",
                "policy__branch",
                "policy__insurance_type",
                "policy__policyholder",
            )
            .filter(
                due_date__gte=start_date,
                due_date__lte=end_date,
                installment_number=1,
            )
            .exclude(cancelled_filter)
            .order_by("due_date")
        )

        # Проверяем наличие данных
        if not payments.exists():
            messages.warning(
                request,
                f"Нет платежей для выбранного периода ({start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')})",
            )
            return redirect("reports:index")

        # Создаем HTTP ответ с CSV
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"payments_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        # Добавляем BOM для корректного отображения в Excel
        response.write("\ufeff")

        writer = csv.writer(response, delimiter=";")

        # Названия месяцев на русском
        month_names_ru = [
            "",
            "Январь",
            "Февраль",
            "Март",
            "Апрель",
            "Май",
            "Июнь",
            "Июль",
            "Август",
            "Сентябрь",
            "Октябрь",
            "Ноябрь",
            "Декабрь",
        ]

        # Заголовки в требуемом порядке
        headers = [
            "Номер ДФА",
            "Лизингополучатель",
            "Страховщик",
            "Страхователь",
            "Описание застрахованного имущества",
            "Страховая сумма",
            "Страховая премия",
            "КВ в процентах",
            "Вид страхования",
            "Филиал",
            "Месяц",
            "Статус",
            "Участие брокера",
        ]
        writer.writerow(headers)

        # Данные
        for payment in payments:
            policy = payment.policy
            kv_percent = (
                "{:.2f}".format(payment.kv_percent_actual)
                if payment.amount and payment.kv_rub
                else ""
            )
            row = [
                policy.dfa_number or "",
                policy.client.client_name if policy.client else "",
                policy.insurer.insurer_name if policy.insurer else "",
                policy.policyholder.client_name if policy.policyholder else "",
                policy.property_description or "",
                str(payment.insurance_sum) if payment.insurance_sum else "",
                str(payment.amount) if payment.amount else "",
                kv_percent,
                policy.insurance_type.name if policy.insurance_type else "",
                policy.branch.branch_name if policy.branch else "",
                month_names_ru[payment.due_date.month] if payment.due_date else "",
                "Новая"
                if payment.year_number == 1 and not policy.renewal_to_old_dfa
                else "Пролонгация",
                "Да" if policy.broker_participation else "Нет",
            ]
            writer.writerow(row)

        # Логируем
        logger.info(
            f"User {request.user.username} exported payments to CSV (period: {start_date} - {end_date}, count: {payments.count()})"
        )

        return response

    except Exception as e:
        logger.error(f"Error exporting payments to CSV: {e}")
        messages.error(request, "Ошибка при создании CSV файла")
        return redirect("reports:index")


@login_required
def export_commission_report(request):
    """Export commission report - paid but not approved by insurer"""
    try:
        # Получаем ID страховой компании из запроса
        insurer_id = request.GET.get("insurer")

        # Проверяем наличие обязательного параметра
        if not insurer_id:
            messages.error(request, "Необходимо выбрать страховую компанию")
            return redirect("reports:index")

        # Проверяем существование страховой компании
        try:
            insurer = Insurer.objects.get(id=insurer_id)
        except Insurer.DoesNotExist:
            messages.error(request, "Страховая компания не найдена")
            return redirect("reports:index")

        # Получаем платежи с оптимизированными запросами
        # Фильтруем: есть дата оплаты, но нет даты согласования СК
        from django.db.models import Count, OuterRef, Subquery

        # Подзапрос для подсчета платежей в том же году того же полиса
        payments_in_year_subquery = (
            PaymentSchedule.objects.filter(
                policy=OuterRef("policy"), year_number=OuterRef("year_number")
            )
            .values("policy", "year_number")
            .annotate(count=Count("id"))
            .values("count")
        )

        payments = (
            PaymentSchedule.objects.select_related(
                "policy",
                "policy__client",
                "policy__insurer",
                "policy__leasing_manager",
                "policy__policyholder",
                "policy__branch",
                "commission_rate",
            )
            .annotate(payments_in_year=Subquery(payments_in_year_subquery))
            .filter(
                policy__insurer_id=insurer_id,
                paid_date__isnull=False,  # Есть дата оплаты
                insurer_date__isnull=True,  # Нет даты согласования СК
                kv_rub__gt=0,  # КВ руб больше нуля
            )
            .order_by("paid_date", "policy__policy_number")
        )

        # Применяем опциональные фильтры
        branch_id = request.GET.get("branch")
        if branch_id:
            payments = payments.filter(policy__branch_id=branch_id)

        # Проверяем наличие данных
        if not payments.exists():
            messages.warning(
                request,
                f"Нет платежей для страховой компании {insurer.insurer_name}, которые оплачены но не согласованы СК",
            )
            return redirect("reports:index")

        # Генерируем отчет
        from .exporters import CommissionReportExporter

        exporter = CommissionReportExporter(
            payments, [], insurer_name=insurer.insurer_name
        )

        # Логируем
        logger.info(
            f"User {request.user.username} exported commission report (insurer: {insurer.insurer_name}, count: {payments.count()})"
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting commission report: {e}")
        messages.error(request, "Ошибка при создании отчета по КВ")
        return redirect("reports:index")


@login_required
def export_monthly_kv_report(request):
    """Export monthly KV report by insurer approval date month/year (admin only)."""
    if not _is_admin_user(request.user):
        messages.error(request, "У вас нет прав для выполнения этого действия")
        return redirect("reports:index")

    try:
        month_param = request.GET.get("kv_month")
        year_param = request.GET.get("kv_year")

        if not month_param or not year_param:
            messages.error(request, "Необходимо выбрать месяц и год")
            return redirect("reports:index")

        try:
            month = int(month_param)
            year = int(year_param)
        except (TypeError, ValueError):
            messages.error(request, "Некорректные значения месяца или года")
            return redirect("reports:index")

        if month < 1 or month > 12:
            messages.error(request, "Месяц должен быть в диапазоне от 1 до 12")
            return redirect("reports:index")

        current_year = timezone.now().year
        if year < 2000 or year > current_year + 5:
            messages.error(request, "Некорректное значение года")
            return redirect("reports:index")

        payments = (
            PaymentSchedule.objects.select_related(
                "policy",
                "policy__insurer",
                "policy__policyholder",
                "policy__branch",
            )
            .filter(
                insurer_date__isnull=False,
                insurer_date__year=year,
                insurer_date__month=month,
                kv_rub__gt=0,
            )
            .order_by(
                "insurer_date",
                "policy__insurer__insurer_name",
                "policy__policy_number",
            )
        )

        if not payments.exists():
            messages.warning(
                request,
                f"Нет данных по КВ за {month:02d}.{year}",
            )
            return redirect("reports:index")

        from .exporters import MonthlyKVReportExporter

        exporter = MonthlyKVReportExporter(payments, [], month=month, year=year)

        logger.info(
            "User %s exported monthly KV report (period: %02d.%s, count: %s)",
            request.user.username,
            month,
            year,
            payments.count(),
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting monthly KV report: {e}")
        messages.error(request, "Ошибка при создании отчета КВ за месяц")
        return redirect("reports:index")


@login_required
def export_three_percent_report(request):
    """Export approved payments for selected quarter to Excel (admin only)."""
    if not _is_admin_user(request.user):
        messages.error(request, "У вас нет прав для выполнения этого действия")
        return redirect("reports:index")

    try:
        quarter_param = request.GET.get("three_percent_quarter")
        year_param = request.GET.get("three_percent_year")

        if not quarter_param or not year_param:
            messages.error(request, "Необходимо выбрать квартал и год")
            return redirect("reports:index")

        try:
            quarter = int(quarter_param)
            year = int(year_param)
        except (TypeError, ValueError):
            messages.error(request, "Некорректные значения квартала или года")
            return redirect("reports:index")

        if quarter < 1 or quarter > 4:
            messages.error(request, "Квартал должен быть в диапазоне от 1 до 4")
            return redirect("reports:index")

        current_year = timezone.now().year
        if year < 2000 or year > current_year + 5:
            messages.error(request, "Некорректное значение года")
            return redirect("reports:index")

        from datetime import date, timedelta

        start_month = (quarter - 1) * 3 + 1
        date_from = date(year, start_month, 1)
        if quarter == 4:
            date_to = date(year, 12, 31)
        else:
            date_to = date(year, start_month + 3, 1) - timedelta(days=1)

        payments = (
            PaymentSchedule.objects.select_related(
                "policy",
                "policy__client",
                "policy__insurer",
                "policy__policyholder",
                "policy__branch",
                "policy__insurance_type",
                "commission_rate",
            )
            .filter(
                insurer_date__gte=date_from,
                insurer_date__lte=date_to,
            )
            .order_by(
                "insurer_date",
                "policy__insurer__insurer_name",
                "policy__policy_number",
                "year_number",
                "installment_number",
            )
        )

        if not payments.exists():
            messages.warning(
                request,
                (
                    "Нет платежей со статусом «Акт согласован СК» "
                    f"за {quarter} квартал {year}"
                ),
            )
            return redirect("reports:index")

        from .exporters import ThreePercentReportExporter

        exporter = ThreePercentReportExporter(
            payments,
            [],
            quarter=quarter,
            year=year,
            date_from=date_from,
            date_to=date_to,
        )

        logger.info(
            "User %s exported three percent report (quarter: Q%s %s, count: %s)",
            request.user.username,
            quarter,
            year,
            payments.count(),
        )

        return exporter.export()

    except Exception as e:
        logger.error(f"Error exporting three percent report: {e}")
        messages.error(request, "Ошибка при создании отчета по 3%")
        return redirect("reports:index")


@login_required
def export_database_backup(request):
    """Скачивание актуального backup-файла базы данных."""
    return _download_backup_file(request, "database")


@login_required
def export_media_backup(request):
    """Скачивание актуального backup-файла media."""
    return _download_backup_file(request, "media")


class ExportsIndexView(LoginRequiredMixin, TemplateView):
    """Главная страница экспорта"""

    template_name = "reports/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Получаем последние использованные шаблоны пользователя
        context["recent_templates"] = CustomExportTemplate.objects.filter(
            user=self.request.user
        )[:5]
        # Получаем список всех страховых компаний для отчета по КВ
        context["insurers"] = Insurer.objects.all().order_by("insurer_name")
        # Получаем список годов для CSV экспорта
        from django.db.models.functions import ExtractYear

        years = (
            Policy.objects.annotate(year=ExtractYear("start_date"))
            .values_list("year", flat=True)
            .distinct()
            .order_by("-year")
        )
        context["years"] = [year for year in years if year]

        kv_years = (
            PaymentSchedule.objects.filter(insurer_date__isnull=False)
            .annotate(year=ExtractYear("insurer_date"))
            .values_list("year", flat=True)
            .distinct()
            .order_by("-year")
        )
        kv_year_choices = [year for year in kv_years if year]
        current_date = timezone.now().date()

        if not kv_year_choices:
            kv_year_choices = [current_date.year]

        context["kv_month_choices"] = [
            (1, "Январь"),
            (2, "Февраль"),
            (3, "Март"),
            (4, "Апрель"),
            (5, "Май"),
            (6, "Июнь"),
            (7, "Июль"),
            (8, "Август"),
            (9, "Сентябрь"),
            (10, "Октябрь"),
            (11, "Ноябрь"),
            (12, "Декабрь"),
        ]
        context["kv_year_choices"] = kv_year_choices

        try:
            selected_kv_month = int(
                self.request.GET.get("kv_month", current_date.month)
            )
        except (TypeError, ValueError):
            selected_kv_month = current_date.month
        if selected_kv_month < 1 or selected_kv_month > 12:
            selected_kv_month = current_date.month

        try:
            selected_kv_year = int(self.request.GET.get("kv_year", kv_year_choices[0]))
        except (TypeError, ValueError):
            selected_kv_year = kv_year_choices[0]
        if selected_kv_year not in kv_year_choices:
            selected_kv_year = kv_year_choices[0]

        context["selected_kv_month"] = selected_kv_month
        context["selected_kv_year"] = selected_kv_year

        three_percent_years = (
            PaymentSchedule.objects.filter(insurer_date__isnull=False)
            .annotate(year=ExtractYear("insurer_date"))
            .values_list("year", flat=True)
            .distinct()
            .order_by("-year")
        )
        three_percent_year_choices = [year for year in three_percent_years if year]
        if not three_percent_year_choices:
            three_percent_year_choices = [current_date.year]

        context["three_percent_quarter_choices"] = [
            (1, "1 квартал"),
            (2, "2 квартал"),
            (3, "3 квартал"),
            (4, "4 квартал"),
        ]
        context["three_percent_year_choices"] = three_percent_year_choices

        default_quarter = (current_date.month - 1) // 3 + 1
        try:
            selected_three_percent_quarter = int(
                self.request.GET.get("three_percent_quarter", default_quarter)
            )
        except (TypeError, ValueError):
            selected_three_percent_quarter = default_quarter
        if selected_three_percent_quarter < 1 or selected_three_percent_quarter > 4:
            selected_three_percent_quarter = default_quarter

        try:
            selected_three_percent_year = int(
                self.request.GET.get(
                    "three_percent_year", three_percent_year_choices[0]
                )
            )
        except (TypeError, ValueError):
            selected_three_percent_year = three_percent_year_choices[0]
        if selected_three_percent_year not in three_percent_year_choices:
            selected_three_percent_year = three_percent_year_choices[0]

        context["selected_three_percent_quarter"] = selected_three_percent_quarter
        context["selected_three_percent_year"] = selected_three_percent_year

        if _is_admin_user(self.request.user):
            context["database_backup_info"] = _get_backup_file_info("database")
            context["media_backup_info"] = _get_backup_file_info("media")

        return context


class CustomExportView(LoginRequiredMixin, FormView):
    """Конструктор кастомного экспорта"""

    template_name = "reports/custom_export.html"
    form_class = CustomExportForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Получаем доступные поля для каждого источника данных
        context["available_fields"] = self.get_available_fields()
        # Получаем сохраненные шаблоны пользователя
        context["templates"] = CustomExportTemplate.objects.filter(
            user=self.request.user
        )
        # Получаем данные для фильтров
        context["filter_data"] = self.get_filter_data()
        return context

    def get_available_fields(self):
        """Возвращает словарь доступных полей для каждого источника"""
        return {
            "policies": {
                "basic": [
                    ("policy_number", "Номер полиса"),
                    ("dfa_number", "Номер ДФА"),
                    ("start_date", "Дата начала страхования"),
                    ("end_date", "Дата окончания страхования"),
                    ("premium_total", "Общая премия"),
                    ("franchise", "Франшиза"),
                    ("policy_active", "Статус полиса"),
                    ("termination_date", "Дата расторжения"),
                    ("dfa_active", "Статус ДФА"),
                    ("broker_participation", "Участие брокера"),
                ],
                "related": [
                    ("client__client_name", "Лизингополучатель"),
                    ("policyholder__client_name", "Страхователь"),
                    ("insurer__insurer_name", "Страховщик"),
                    ("insurance_type__name", "Вид страхования"),
                    ("branch__branch_name", "Филиал"),
                ],
            },
            "payments": {
                "basic": [
                    ("year_number", "Год (в связке год/платеж)"),
                    ("installment_number", "Платеж (в связке год/платеж)"),
                    ("due_date", "Дата платежа (по договору)"),
                    ("amount", "Страховая премия"),
                    ("insurance_sum", "Страховая сумма"),
                    ("kv_rub", "КВ (в руб)"),
                    ("paid_date", "Дата фактической оплаты"),
                    ("insurer_date", "Дата согласования акта с СК"),
                ],
                "related": [
                    ("policy__policy_number", "Номер полиса"),
                    ("policy__dfa_number", "Номер ДФА"),
                    ("policy__client__client_name", "Лизингополучатель"),
                    ("policy__policyholder__client_name", "Страхователь"),
                    ("policy__insurer__insurer_name", "Страховщик"),
                    ("policy__insurance_type__name", "Вид страхования"),
                    ("policy__branch__branch_name", "Филиал"),
                    ("commission_rate__kv_percent", "КВ в %"),
                ],
            },
        }

    def get_filter_data(self):
        """Возвращает данные для фильтров"""
        try:
            from apps.insurers.models import Branch, InsuranceType
            import json

            data = {
                "branches": list(Branch.objects.all().values("id", "branch_name")),
                "insurers": list(Insurer.objects.all().values("id", "insurer_name")),
                "insurance_types": list(
                    InsuranceType.objects.all().values("id", "name")
                ),
            }
            return json.dumps(data)
        except Exception as e:
            logger.error(f"Error getting filter data: {e}")
            return json.dumps({"branches": [], "insurers": [], "insurance_types": []})

    def post(self, request, *args, **kwargs):
        """Обработка POST запросов"""
        action = request.POST.get("action")

        if action == "export":
            return self.export_report(request)
        elif action == "save_template":
            return self.save_template(request)
        elif action == "load_template":
            return self.load_template(request)

        return super().post(request, *args, **kwargs)

    def export_report(self, request):
        """Генерирует и возвращает Excel файл"""
        data_source = request.POST.get("data_source")
        selected_fields = request.POST.getlist("fields")
        fields_order = request.POST.get("fields_order")

        # Если есть порядок полей, используем его, иначе используем порядок из checkbox
        if fields_order:
            try:
                import json

                ordered_fields = json.loads(fields_order)
                # Проверяем, что все поля из порядка есть в выбранных полях
                selected_fields = [
                    field for field in ordered_fields if field in selected_fields
                ]
            except (json.JSONDecodeError, TypeError):
                # Если не удалось парсить порядок, используем обычный список
                pass

        if not selected_fields:
            messages.error(request, "Выберите хотя бы одно поле для экспорта")
            return redirect("reports:custom_export")

        try:
            # Получаем queryset с примененными фильтрами
            queryset = self.get_filtered_queryset(data_source, request.POST)

            # Проверяем наличие данных
            if not queryset.exists():
                messages.warning(
                    request, "Нет данных для экспорта с выбранными фильтрами"
                )
                return redirect("reports:custom_export")

            # Оптимизируем запрос
            queryset = self.optimize_queryset(queryset, selected_fields)

            # Генерируем отчет
            exporter = CustomExporter(queryset, selected_fields, data_source)

            # Логируем экспорт
            logger.info(
                f"User {request.user.username} exported {data_source} with {len(selected_fields)} fields"
            )

            return exporter.export()

        except DatabaseError as e:
            logger.error(f"Database error in report generation: {e}")
            messages.error(request, "Ошибка при получении данных. Попробуйте позже")
            return redirect("reports:custom_export")
        except Exception as e:
            logger.error(f"Error generating Excel file: {e}")
            messages.error(request, "Ошибка при создании файла. Попробуйте позже")
            return redirect("reports:custom_export")

    def get_filtered_queryset(self, data_source, data):
        """Получает queryset с примененными фильтрами"""
        model_map = {
            "policies": Policy,
            "payments": PaymentSchedule,
        }
        filter_map = {
            "policies": PolicyExportFilter,
            "payments": PaymentExportFilter,
        }

        model = model_map[data_source]
        filter_class = filter_map[data_source]

        queryset = model.objects.all()
        filterset = filter_class(data, queryset=queryset)

        return filterset.qs

    def optimize_queryset(self, queryset, fields):
        """Оптимизирует queryset на основе выбранных полей"""
        from django.core.exceptions import FieldDoesNotExist

        select_related_fields = set()
        root_model = queryset.model

        for field_path in fields:
            if "__" not in field_path:
                continue

            parts = field_path.split("__")
            current_model = root_model
            relation_chain = []

            # Add every intermediate FK/O2O relation in the chain:
            # policy__client__client_name -> policy, policy__client
            for part in parts[:-1]:
                try:
                    field_obj = current_model._meta.get_field(part)
                except FieldDoesNotExist:
                    break

                if not field_obj.is_relation:
                    break

                if field_obj.many_to_many or field_obj.one_to_many:
                    # select_related does not work for M2M/reverse relations
                    break

                relation_chain.append(part)
                select_related_fields.add("__".join(relation_chain))
                current_model = field_obj.related_model

        if select_related_fields:
            queryset = queryset.select_related(*sorted(select_related_fields))

        return queryset

    def save_template(self, request):
        """Сохраняет шаблон экспорта"""
        name = request.POST.get("template_name")
        data_source = request.POST.get("data_source")
        selected_fields = request.POST.getlist("fields")
        fields_order = request.POST.get("fields_order")

        if not name:
            messages.error(request, "Укажите название шаблона")
            return redirect("reports:custom_export")

        if not selected_fields:
            messages.error(
                request, "Выберите хотя бы одно поле для сохранения в шаблон"
            )
            return redirect("reports:custom_export")

        # Если есть порядок полей, используем его
        if fields_order:
            try:
                import json

                ordered_fields = json.loads(fields_order)
                # Проверяем, что все поля из порядка есть в выбранных полях
                selected_fields = [
                    field for field in ordered_fields if field in selected_fields
                ]
            except (json.JSONDecodeError, TypeError):
                # Если не удалось парсить порядок, используем обычный список
                pass

        # Собираем фильтры - все поля, которые начинаются с названий полей фильтров
        filters = {}
        filter_fields = [
            # Для полисов
            "policy_number",
            "dfa_number",
            "client__client_name",
            "policyholder__client_name",
            "start_date_from",
            "start_date_to",
            "end_date_from",
            "end_date_to",
            "insurer",
            "branch",
            "insurance_type",
            "policy_active",
            "dfa_active",
            "broker_participation",
            # Для платежей
            "policy__policy_number",
            "policy__client__client_name",
            "policy__policyholder__client_name",
            "due_date_from",
            "due_date_to",
            "paid_date_from",
            "paid_date_to",
            "insurer_date_from",
            "insurer_date_to",
            "is_paid",
            "policy__insurer",
            "policy__branch",
            "year_number",
            "installment_number",
        ]

        for field in filter_fields:
            value = request.POST.get(field)
            if value:
                filters[field] = value

        config = {"fields": selected_fields, "filters": filters}

        try:
            template, created = CustomExportTemplate.objects.update_or_create(
                user=request.user,
                name=name,
                defaults={"data_source": data_source, "config": config},
            )

            if created:
                messages.success(request, f'Шаблон "{name}" сохранен')
            else:
                messages.success(request, f'Шаблон "{name}" обновлен')

        except Exception as e:
            logger.error(f"Error saving template: {e}")
            messages.error(request, "Ошибка при сохранении шаблона")

        return redirect("reports:custom_export")

    def load_template(self, request):
        """Загружает шаблон экспорта"""
        template_id = request.POST.get("template_id")

        try:
            template = CustomExportTemplate.objects.get(
                id=template_id, user=request.user
            )

            # Возвращаем данные шаблона в JSON
            return JsonResponse(
                {
                    "success": True,
                    "data_source": template.data_source,
                    "fields": template.config.get("fields", []),
                    "filters": template.config.get("filters", {}),
                }
            )

        except CustomExportTemplate.DoesNotExist:
            return JsonResponse(
                {"success": False, "error": "Шаблон не найден"}, status=404
            )
        except Exception as e:
            logger.error(f"Error loading template: {e}")
            return JsonResponse(
                {"success": False, "error": "Ошибка при загрузке шаблона"}, status=500
            )


class DeleteTemplateView(LoginRequiredMixin, View):
    """Удаление шаблона экспорта"""

    def post(self, request, pk):
        try:
            template = CustomExportTemplate.objects.get(pk=pk, user=request.user)
            template_name = template.name
            template.delete()
            messages.success(request, f'Шаблон "{template_name}" удален')
        except CustomExportTemplate.DoesNotExist:
            messages.error(request, "Шаблон не найден")
        except Exception as e:
            logger.error(f"Error deleting template: {e}")
            messages.error(request, "Ошибка при удалении шаблона")

        return redirect("reports:custom_export")
