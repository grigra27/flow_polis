from django.contrib import admin
from django.utils.html import format_html
from django.contrib.admin import SimpleListFilter
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode
from decimal import Decimal
from .models import Policy, PaymentSchedule, PolicyInfo


class InsuranceSumRangeFilter(SimpleListFilter):
    """
    Custom filter for filtering PaymentSchedule by insurance_sum ranges.
    
    **Validates: Requirements 4.4**
    """
    title = 'диапазон страховой суммы'
    parameter_name = 'insurance_sum_range'
    
    def lookups(self, request, model_admin):
        """Define the filter options."""
        return (
            ('0-500k', 'До 500 000 ₽'),
            ('500k-1m', '500 000 - 1 000 000 ₽'),
            ('1m-5m', '1 000 000 - 5 000 000 ₽'),
            ('5m-10m', '5 000 000 - 10 000 000 ₽'),
            ('10m+', 'Более 10 000 000 ₽'),
        )
    
    def queryset(self, request, queryset):
        """Filter the queryset based on the selected range."""
        if self.value() == '0-500k':
            return queryset.filter(insurance_sum__lt=Decimal('500000'))
        elif self.value() == '500k-1m':
            return queryset.filter(
                insurance_sum__gte=Decimal('500000'),
                insurance_sum__lt=Decimal('1000000')
            )
        elif self.value() == '1m-5m':
            return queryset.filter(
                insurance_sum__gte=Decimal('1000000'),
                insurance_sum__lt=Decimal('5000000')
            )
        elif self.value() == '5m-10m':
            return queryset.filter(
                insurance_sum__gte=Decimal('5000000'),
                insurance_sum__lt=Decimal('10000000')
            )
        elif self.value() == '10m+':
            return queryset.filter(insurance_sum__gte=Decimal('10000000'))
        return queryset


class PaymentScheduleInline(admin.TabularInline):
    model = PaymentSchedule
    extra = 1
    fields = [
        'year_number', 'installment_number', 'due_date', 'amount',
        'insurance_sum',
        'commission_rate', 'kv_rub', 'paid_date', 'insurer_date', 'payment_info'
    ]
    autocomplete_fields = ['commission_rate']
    
    class Media:
        js = ('policies/js/copy_payment_inline.js',)
        css = {
            'all': ('policies/css/copy_payment_inline.css',)
        }
        css = {
            'all': ('policies/css/copy_payment_inline.css',)
        }


class PolicyInfoInline(admin.TabularInline):
    model = PolicyInfo
    extra = 1
    autocomplete_fields = ['tag']


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = [
        'policy_number', 'dfa_number', 'client', 'insurer',
        'start_date', 'end_date', 'premium_total',
        'policy_status', 'dfa_status'
    ]
    list_filter = [
        'policy_active', 'dfa_active', 'insurance_type',
        'branch', 'insurer', 'start_date'
    ]
    search_fields = [
        'policy_number', 'dfa_number',
        'client__client_name', 'insurer__insurer_name'
    ]
    autocomplete_fields = ['client', 'policyholder', 'insurer', 'insurance_type', 'branch']
    readonly_fields = ['premium_total', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Основная информация', {
            'fields': (
                'policy_number', 'dfa_number',
                'client', 'policyholder', 'insurer'
            )
        }),
        ('Детали страхования', {
            'fields': (
                'insurance_type', 'property_description',
                'franchise',
                'start_date', 'end_date'
            )
        }),
        ('Финансы', {
            'fields': ('premium_total',)
        }),
        ('Организационная информация', {
            'fields': ('branch', 'leasing_manager')
        }),
        ('Дополнительная информация', {
            'fields': ('info3', 'info4')
        }),
        ('Статусы', {
            'fields': ('policy_active', 'dfa_active')
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [PaymentScheduleInline, PolicyInfoInline]
    
    def policy_status(self, obj):
        if obj.policy_active:
            return format_html('<span style="color: green;">✓ Активен</span>')
        return format_html('<span style="color: red;">✗ Закрыт</span>')
    policy_status.short_description = 'Статус полиса'
    
    def dfa_status(self, obj):
        if obj.dfa_active:
            return format_html('<span style="color: green;">✓ Активен</span>')
        return format_html('<span style="color: red;">✗ Закрыт</span>')
    dfa_status.short_description = 'Статус ДФА'


@admin.register(PaymentSchedule)
class PaymentScheduleAdmin(admin.ModelAdmin):
    list_display = [
        'policy', 'year_number', 'installment_number',
        'due_date', 'amount', 'insurance_sum', 'kv_rub', 'payment_status'
    ]
    list_filter = ['due_date', 'paid_date', InsuranceSumRangeFilter]
    search_fields = ['policy__policy_number', 'policy__client__client_name']
    autocomplete_fields = ['policy', 'commission_rate']
    date_hierarchy = 'due_date'
    actions = ['copy_payments']
    
    @admin.action(description='Копировать выбранные платежи')
    def copy_payments(self, request, queryset):
        """
        Copy selected payments by redirecting to add form with pre-filled data.
        
        This action creates copies of selected payments by redirecting to the
        add form with all field values pre-populated via GET parameters.
        The user can then modify the values before saving.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
        """
        # Get the first payment to copy
        # If multiple payments are selected, we copy the first one
        # (Django admin actions typically work on one item at a time for this use case)
        payment = queryset.first()
        
        if not payment:
            return
        
        # Build dictionary of field values to copy
        # Exclude id, created_at, updated_at as per requirements
        copy_data = {
            'policy': payment.policy.id,
            'year_number': payment.year_number,
            'installment_number': payment.installment_number,
            'due_date': payment.due_date,
            'amount': payment.amount,
            'insurance_sum': payment.insurance_sum,
            'kv_rub': payment.kv_rub,
            'payment_info': payment.payment_info,
        }
        
        # Add optional fields if they exist
        if payment.commission_rate:
            copy_data['commission_rate'] = payment.commission_rate.id
        if payment.paid_date:
            copy_data['paid_date'] = payment.paid_date
        if payment.insurer_date:
            copy_data['insurer_date'] = payment.insurer_date
        
        # Build URL with query parameters
        add_url = reverse('admin:policies_paymentschedule_add')
        query_string = urlencode(copy_data)
        redirect_url = f'{add_url}?{query_string}'
        
        return redirect(redirect_url)
    
    def payment_status(self, obj):
        if obj.is_paid:
            return format_html('<span style="color: green;">✓ Оплачен</span>')
        elif obj.is_overdue:
            return format_html('<span style="color: red;">✗ Просрочен</span>')
        return format_html('<span style="color: orange;">⏳ Ожидается</span>')
    payment_status.short_description = 'Статус'
