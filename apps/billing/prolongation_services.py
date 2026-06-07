"""Сервисный слой раздела «Пролонгация».

Раздел переносит в веб-интерфейс готовый экспорт «Пролонгация»
(apps.reports PolicyExpirationExporter): сотрудник выбирает месяц, визуально
проверяет договоры с окончанием срока страхования в этом месяце и отправляет
ту же таблицу одним письмом с Excel-вложением.

В отличие от очередных взносов, задач по отдельным договорам нет — выборка
строится на лету из Policy, а ProlongationBatch создаётся лениво при первой
отправке за месяц (нужен как content_object для письма и истории отправок).
"""

import calendar
from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Count, Q
from django.db.models.functions import ExtractMonth, ExtractYear
from django.http import QueryDict
from django.utils import timezone

from apps.insurers.models import Branch, Insurer
from apps.policies.models import Policy
from apps.reports.exporters import PolicyExpirationExporter

from .models import MONTH_NAMES_RU, ProlongationBatch
from .services import add_months, parse_int_list_query_param, parse_period_code

# Горизонт навигации: текущий месяц + 6 месяцев вперёд.
VISIBLE_FUTURE_MONTHS = 6

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def visible_prolongation_months(today=None):
    """Список первых дней месяцев для чипсов навигации (текущий … +6)."""
    today = today or timezone.localdate()
    current_month = date(today.year, today.month, 1)
    return [
        add_months(current_month, offset)
        for offset in range(0, VISIBLE_FUTURE_MONTHS + 1)
    ]


def resolve_selected_month(months, code=None):
    """Возвращает (year, month) выбранного периода.

    Если в query-параметре пришёл корректный код — берём его (даже если он
    за пределами видимого горизонта). Иначе — первый (текущий) месяц.
    """
    parsed = parse_period_code(code)
    if parsed:
        return parsed
    first = months[0]
    return first.year, first.month


def month_bounds(year, month):
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


def get_or_create_batch(year, month):
    batch, _ = ProlongationBatch.objects.get_or_create(year=year, month=month)
    return batch


def get_existing_batch(year, month):
    return ProlongationBatch.objects.filter(year=year, month=month).first()


def get_prolongation_policies(year, month, request_get=None, branch_ids_filter=None):
    """Договоры пролонгации за месяц.

    Выборка повторяет reports.views.export_policy_expiration: активные полисы
    с окончанием страхования в указанном месяце. Статус ДФА и участие брокера
    не фильтруются — такие строки нужны в таблице и помечаются примечанием.
    Опциональные фильтры (страховщик, филиал, поиск) применяются только для
    удобного просмотра в вебе; на состав письма они не влияют.
    """
    period_start, period_end = month_bounds(year, month)
    policies = (
        Policy.objects.select_related(
            "client",
            "insurer",
            "branch",
            "insurance_type",
            "policyholder",
            "leasing_manager",
        )
        .filter(
            end_date__gte=period_start,
            end_date__lte=period_end,
            policy_active=True,
        )
        .order_by("branch__branch_name", "end_date", "policy_number")
    )

    if request_get is None:
        request_get = QueryDict()

    insurer_id = request_get.get("insurer")
    if insurer_id:
        policies = policies.filter(insurer_id=insurer_id)

    if branch_ids_filter is not None:
        if not branch_ids_filter:
            return policies.none()
        policies = policies.filter(branch_id__in=branch_ids_filter)
    else:
        branch_ids = parse_int_list_query_param(request_get, "branch")
        if branch_ids:
            policies = policies.filter(branch_id__in=branch_ids)

    search = (request_get.get("q") or "").strip()
    if search:
        policies = policies.filter(
            Q(policy_number__icontains=search)
            | Q(dfa_number__icontains=search)
            | Q(client__client_name__icontains=search)
            | Q(policyholder__client_name__icontains=search)
            | Q(property_description__icontains=search)
            | Q(insurer__insurer_name__icontains=search)
        )

    return policies


def build_prolongation_month_options(months, selected_year, selected_month):
    """Чипсы навигации со счётчиком договоров в каждом месяце."""
    if not months:
        return []

    min_start = date(months[0].year, months[0].month, 1)
    last = months[-1]
    _, last_day = calendar.monthrange(last.year, last.month)
    max_end = date(last.year, last.month, last_day)

    counts = (
        Policy.objects.filter(
            end_date__gte=min_start,
            end_date__lte=max_end,
            policy_active=True,
        )
        .annotate(
            period_year=ExtractYear("end_date"),
            period_month=ExtractMonth("end_date"),
        )
        .values("period_year", "period_month")
        .annotate(total=Count("id"))
    )
    count_map = {
        (item["period_year"], item["period_month"]): item["total"] for item in counts
    }

    options = []
    for month in months:
        options.append(
            {
                "year": month.year,
                "month": month.month,
                "code": f"{month.year:04d}-{month.month:02d}",
                "label": f"{MONTH_NAMES_RU.get(month.month, month.month)} {month.year}",
                "total": count_map.get((month.year, month.month), 0),
                "selected": (
                    month.year == selected_year and month.month == selected_month
                ),
            }
        )
    return options


def build_prolongation_attachment(batch, policies):
    """Генерирует Excel-таблицу пролонгации за месяц как готовое вложение."""
    exporter = PolicyExpirationExporter(
        policies, [], date_from=batch.starts_on, date_to=batch.ends_on
    )
    workbook = exporter.build_workbook()
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"prolongation_{batch.code}.xlsx"
    return SimpleUploadedFile(filename, buffer.read(), content_type=XLSX_CONTENT_TYPE)


def get_filter_options():
    return {
        "branches": Branch.objects.order_by("branch_name"),
        "insurers": Insurer.objects.order_by("insurer_name"),
    }
