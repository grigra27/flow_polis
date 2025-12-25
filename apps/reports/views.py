from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, FormView, View
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db import DatabaseError
from apps.policies.models import Policy, PaymentSchedule
from apps.clients.models import Client
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
            )
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

        # Получаем ВСЕ полисы с окончанием страхования в заданном диапазоне
        # Включаем все записи независимо от статуса полиса или ДФА
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
            .filter(end_date__gte=date_from, end_date__lte=date_to)
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
    """Export policies to CSV format by year"""
    # Проверяем права администратора
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "У вас нет прав для выполнения этого действия")
        return redirect("reports:index")

    try:
        import csv
        from django.utils import timezone

        # Получаем параметр года из запроса
        year_param = request.GET.get("year")

        # Проверяем наличие обязательного параметра
        if not year_param:
            messages.error(request, "Необходимо выбрать год")
            return redirect("reports:index")

        # Получаем полисы с оптимизированными запросами
        policies = Policy.objects.select_related(
            "client",
            "insurer",
            "branch",
            "insurance_type",
            "policyholder",
            "leasing_manager",
        ).all()

        # Применяем фильтр по году, если не выбрано "Все годы"
        if year_param != "all":
            try:
                year = int(year_param)
                policies = policies.filter(start_date__year=year)
            except ValueError:
                messages.error(request, "Неверный формат года")
                return redirect("reports:index")

        # Проверяем наличие данных
        if not policies.exists():
            messages.warning(
                request,
                f"Нет полисов для выбранного периода",
            )
            return redirect("reports:index")

        # Создаем HTTP ответ с CSV
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        year_str = year_param if year_param == "all" else f"{year_param}"
        filename = f"policies_{year_str}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        # Добавляем BOM для корректного отображения в Excel
        response.write("\ufeff")

        writer = csv.writer(response, delimiter=";")

        # Заголовки
        headers = [
            "Номер полиса",
            "Номер ДФА",
            "Клиент",
            "Страховщик",
            "Вид страхования",
            "Филиал",
            "Дата начала",
            "Дата окончания",
            "Общая премия",
            "Франшиза",
            "Страхователь",
            "Менеджер по лизингу",
            "Статус полиса",
            "Статус ДФА",
            "Участие брокера",
            "Дата расторжения",
        ]
        writer.writerow(headers)

        # Данные
        for policy in policies:
            row = [
                policy.policy_number or "",
                policy.dfa_number or "",
                policy.client.client_name if policy.client else "",
                policy.insurer.insurer_name if policy.insurer else "",
                policy.insurance_type.name if policy.insurance_type else "",
                policy.branch.branch_name if policy.branch else "",
                policy.start_date.strftime("%d.%m.%Y") if policy.start_date else "",
                policy.end_date.strftime("%d.%m.%Y") if policy.end_date else "",
                str(policy.premium_total) if policy.premium_total else "",
                str(policy.franchise) if policy.franchise else "",
                policy.policyholder.client_name if policy.policyholder else "",
                policy.leasing_manager.manager_name if policy.leasing_manager else "",
                "Активен" if policy.policy_active else "Неактивен",
                "Активен" if policy.dfa_active else "Неактивен",
                "Да" if policy.broker_participation else "Нет",
                policy.termination_date.strftime("%d.%m.%Y")
                if policy.termination_date
                else "",
            ]
            writer.writerow(row)

        # Логируем
        logger.info(
            f"User {request.user.username} exported policies to CSV (year: {year_param}, count: {policies.count()})"
        )

        return response

    except Exception as e:
        logger.error(f"Error exporting policies to CSV: {e}")
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
                    ("start_date", "Дата начала"),
                    ("end_date", "Дата окончания"),
                    ("premium_total", "Общая премия"),
                    ("franchise", "Франшиза"),
                    ("policy_active", "Статус полиса"),
                    ("termination_date", "Дата расторжения"),
                    ("dfa_active", "Статус ДФА"),
                    ("broker_participation", "Участие брокера"),
                ],
                "related": [
                    ("client__client_name", "Клиент"),
                    ("insurer__insurer_name", "Страховщик"),
                    ("insurance_type__name", "Вид страхования"),
                    ("branch__branch_name", "Филиал"),
                ],
            },
            "payments": {
                "basic": [
                    ("year_number", "Год"),
                    ("installment_number", "Платеж №"),
                    ("due_date", "Дата платежа"),
                    ("amount", "Сумма"),
                    ("insurance_sum", "Страховая сумма"),
                    ("kv_rub", "КВ руб"),
                    ("paid_date", "Дата оплаты"),
                    ("insurer_date", "Дата согласования акта с СК"),
                ],
                "related": [
                    ("policy__policy_number", "Номер полиса"),
                    ("policy__dfa_number", "Номер ДФА"),
                    ("policy__client__client_name", "Клиент"),
                    ("policy__insurer__insurer_name", "Страховщик"),
                    ("policy__branch__branch_name", "Филиал"),
                    ("commission_rate__kv_percent", "КВ %"),
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
        select_related_fields = []

        for field in fields:
            if "__" in field:
                # Извлекаем связанную модель (первый уровень)
                parts = field.split("__")
                related_field = parts[0]
                if related_field not in select_related_fields:
                    select_related_fields.append(related_field)

        if select_related_fields:
            queryset = queryset.select_related(*select_related_fields)

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
            "due_date_from",
            "due_date_to",
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
