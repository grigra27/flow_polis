from django.contrib import admin
from django.utils.html import format_html
from .models import Policy, PaymentSchedule, PolicyInfo


class PaymentScheduleInline(admin.TabularInline):
    model = PaymentSchedule
    extra = 1
    fields = [
        'year_number', 'installment_number', 'due_date', 'amount',
        'commission_rate', 'kv_rub', 'paid_date', 'insurer_date', 'payment_info'
    ]
    autocomplete_fields = ['commission_rate']


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
                'property_value', 'franchise',
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
        'due_date', 'amount', 'kv_rub', 'payment_status'
    ]
    list_filter = ['due_date', 'paid_date']
    search_fields = ['policy__policy_number', 'policy__client__client_name']
    autocomplete_fields = ['policy', 'commission_rate']
    date_hierarchy = 'due_date'
    
    def payment_status(self, obj):
        if obj.is_paid:
            return format_html('<span style="color: green;">✓ Оплачен</span>')
        elif obj.is_overdue:
            return format_html('<span style="color: red;">✗ Просрочен</span>')
        return format_html('<span style="color: orange;">⏳ Ожидается</span>')
    payment_status.short_description = 'Статус'
