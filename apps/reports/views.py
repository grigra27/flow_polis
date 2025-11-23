from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from openpyxl import Workbook
from apps.policies.models import Policy, PaymentSchedule


@login_required
def reports_index(request):
    """Reports main page"""
    return render(request, 'reports/index.html')


@login_required
def export_policies_excel(request):
    """Export policies to Excel"""
    policies = Policy.objects.select_related(
        'client', 'insurer', 'branch', 'insurance_type'
    ).all()
    
    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Полисы"
    
    # Headers
    headers = [
        'Номер полиса', 'Номер ДФА', 'Клиент', 'Страховщик',
        'Вид страхования', 'Филиал', 'Дата начала', 'Дата окончания',
        'Стоимость имущества', 'Общая премия', 'Франшиза',
        'Статус полиса', 'Статус ДФА'
    ]
    ws.append(headers)
    
    # Data
    for policy in policies:
        ws.append([
            policy.policy_number,
            policy.dfa_number,
            policy.client.client_name,
            policy.insurer.insurer_name,
            policy.insurance_type.name,
            policy.branch.branch_name,
            policy.start_date.strftime('%d.%m.%Y'),
            policy.end_date.strftime('%d.%m.%Y'),
            float(policy.property_value),
            float(policy.premium_total),
            float(policy.franchise),
            'Активен' if policy.policy_active else 'Закрыт',
            'Активен' if policy.dfa_active else 'Закрыт',
        ])
    
    # Prepare response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=policies.xlsx'
    wb.save(response)
    
    return response


@login_required
def export_payments_excel(request):
    """Export payment schedule to Excel"""
    payments = PaymentSchedule.objects.select_related(
        'policy', 'policy__client', 'policy__insurer', 'commission_rate'
    ).all()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "График платежей"
    
    headers = [
        'Номер полиса', 'Клиент', 'Год', 'Платеж №',
        'Дата платежа', 'Сумма', 'КВ %', 'КВ руб',
        'Дата оплаты', 'Дата согласования СК', 'Статус'
    ]
    ws.append(headers)
    
    for payment in payments:
        status = 'Оплачен' if payment.is_paid else ('Просрочен' if payment.is_overdue else 'Ожидается')
        ws.append([
            payment.policy.policy_number,
            payment.policy.client.client_name,
            payment.year_number,
            payment.installment_number,
            payment.due_date.strftime('%d.%m.%Y'),
            float(payment.amount),
            float(payment.commission_rate.kv_percent) if payment.commission_rate else 0,
            float(payment.kv_rub),
            payment.paid_date.strftime('%d.%m.%Y') if payment.paid_date else '',
            payment.insurer_date.strftime('%d.%m.%Y') if payment.insurer_date else '',
            status,
        ])
    
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=payments.xlsx'
    wb.save(response)
    
    return response
