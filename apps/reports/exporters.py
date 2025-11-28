from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from datetime import date
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class BaseExporter:
    """Базовый класс для всех экспортеров"""
    
    def __init__(self, queryset, fields):
        self.queryset = queryset
        self.fields = fields
    
    def export(self):
        """Генерирует Excel файл и возвращает HttpResponse"""
        wb = Workbook()
        ws = wb.active
        
        # Заголовки
        headers = self.get_headers()
        ws.append(headers)
        
        # Данные
        for obj in self.queryset:
            row = self.get_row_data(obj)
            ws.append(row)
        
        # Форматирование
        self.apply_formatting(ws)
        
        return self.create_response(wb)
    
    def get_headers(self):
        """Возвращает список заголовков"""
        raise NotImplementedError('Subclasses must implement get_headers()')
    
    def get_row_data(self, obj):
        """Возвращает данные строки для объекта"""
        raise NotImplementedError('Subclasses must implement get_row_data()')
    
    def apply_formatting(self, ws):
        """Применяет форматирование к листу"""
        # Базовое форматирование можно добавить здесь
        pass
    
    def create_response(self, wb):
        """Создает HttpResponse с Excel файлом"""
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{self.get_filename()}_{timestamp}.xlsx'
        response['Content-Disposition'] = f'attachment; filename={filename}'
        wb.save(response)
        return response
    
    def get_filename(self):
        """Возвращает базовое имя файла"""
        return 'report'
    
    def format_value(self, value):
        """Форматирует значение для Excel"""
        if isinstance(value, date):
            return value.strftime('%d.%m.%Y')
        elif isinstance(value, Decimal):
            return float(value)
        elif isinstance(value, bool):
            return 'Да' if value else 'Нет'
        elif value is None:
            return ''
        return value


class CustomExporter(BaseExporter):
    """Экспортер для кастомного экспорта с динамическими полями"""
    
    FIELD_LABELS = {
        'policies': {
            'policy_number': 'Номер полиса',
            'dfa_number': 'Номер ДФА',
            'client__client_name': 'Клиент',
            'insurer__insurer_name': 'Страховщик',
            'insurance_type__name': 'Вид страхования',
            'branch__branch_name': 'Филиал',
            'start_date': 'Дата начала',
            'end_date': 'Дата окончания',
            'property_value': 'Стоимость имущества',
            'premium_total': 'Общая премия',
            'franchise': 'Франшиза',
            'policy_active': 'Статус полиса',
            'termination_date': 'Дата расторжения',
            'dfa_active': 'Статус ДФА',
            'broker_participation': 'Участие брокера',
        },
        'payments': {
            'policy__policy_number': 'Номер полиса',
            'policy__dfa_number': 'Номер ДФА',
            'policy__client__client_name': 'Клиент',
            'policy__insurer__insurer_name': 'Страховщик',
            'policy__branch__branch_name': 'Филиал',
            'year_number': 'Год',
            'installment_number': 'Платеж №',
            'due_date': 'Дата платежа',
            'amount': 'Сумма',
            'insurance_sum': 'Страховая сумма',
            'commission_rate__kv_percent': 'КВ %',
            'kv_rub': 'КВ руб',
            'paid_date': 'Дата оплаты',
            'insurer_date': 'Дата согласования СК',
        },
        'clients': {
            'client_name': 'Название клиента',
            'client_inn': 'ИНН',
            'client_address': 'Адрес',
            'client_phone': 'Телефон',
            'client_email': 'Email',
        },
        'insurers': {
            'insurer_name': 'Название страховщика',
            'insurer_inn': 'ИНН',
            'insurer_address': 'Адрес',
            'insurer_phone': 'Телефон',
            'insurer_email': 'Email',
        },
    }
    
    def __init__(self, queryset, fields, data_source):
        super().__init__(queryset, fields)
        self.data_source = data_source
    
    def get_headers(self):
        """Возвращает список заголовков на основе выбранных полей"""
        return [self.FIELD_LABELS[self.data_source].get(f, f) for f in self.fields]
    
    def get_row_data(self, obj):
        """Возвращает данные строки для объекта"""
        row = []
        for field in self.fields:
            value = self.get_field_value(obj, field)
            row.append(value)
        return row
    
    def get_field_value(self, obj, field):
        """Получает значение поля, поддерживая вложенные поля (через __)"""
        parts = field.split('__')
        value = obj
        for part in parts:
            if value is None:
                break
            value = getattr(value, part, None)
        return self.format_value(value)
    
    def get_filename(self):
        """Возвращает базовое имя файла на основе источника данных"""
        return f'custom_export_{self.data_source}'


class PolicyExporter(BaseExporter):
    """Экспортер для готового экспорта по полисам"""
    
    def get_filename(self):
        """Возвращает базовое имя файла"""
        return 'policies'
    
    def get_headers(self):
        """Возвращает список заголовков"""
        return [
            'Номер полиса', 'Номер ДФА', 'Клиент', 'Страховщик',
            'Вид страхования', 'Филиал', 'Дата начала', 'Дата окончания',
            'Общая премия', 'Франшиза',
            'Статус полиса', 'Дата расторжения', 'Статус ДФА'
        ]
    
    def get_row_data(self, policy):
        """Возвращает данные строки для полиса"""
        return [
            policy.policy_number,
            policy.dfa_number,
            policy.client.client_name,
            policy.insurer.insurer_name,
            policy.insurance_type.name,
            policy.branch.branch_name,
            self.format_value(policy.start_date),
            self.format_value(policy.end_date),
            self.format_value(policy.premium_total),
            self.format_value(policy.franchise),
            'Активен' if policy.policy_active else 'Расторгнут',
            self.format_value(policy.termination_date),
            'Активен' if policy.dfa_active else 'Закрыт',
        ]


class PaymentExporter(BaseExporter):
    """Экспортер для готового экспорта по платежам"""
    
    def get_filename(self):
        """Возвращает базовое имя файла"""
        return 'payments'
    
    def get_headers(self):
        """Возвращает список заголовков"""
        return [
            'Номер полиса', 'Клиент', 'Год', 'Платеж №',
            'Дата платежа', 'Сумма', 'Страховая сумма', 'КВ %', 'КВ руб',
            'Дата оплаты', 'Дата согласования СК', 'Статус'
        ]
    
    def get_row_data(self, payment):
        """Возвращает данные строки для платежа"""
        # Определение статуса
        if payment.is_paid:
            status = 'Оплачен'
        elif payment.is_cancelled:
            status = 'Отменен'
        elif payment.is_overdue:
            status = 'Просрочен'
        else:
            status = 'Ожидается'
        
        return [
            payment.policy.policy_number,
            payment.policy.client.client_name,
            payment.year_number,
            payment.installment_number,
            self.format_value(payment.due_date),
            self.format_value(payment.amount),
            self.format_value(payment.insurance_sum),
            int(round(float(payment.commission_rate.kv_percent))) if payment.commission_rate else 0,
            self.format_value(payment.kv_rub),
            self.format_value(payment.paid_date),
            self.format_value(payment.insurer_date),
            status,
        ]
