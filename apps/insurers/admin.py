from django.contrib import admin
from .models import Insurer, Branch, InsuranceType, InfoTag, CommissionRate


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = ['insurer_name', 'contacts', 'has_logo']
    search_fields = ['insurer_name']
    fields = ['insurer_name', 'logo', 'contacts', 'notes']
    readonly_fields = ['logo_preview']
    
    def has_logo(self, obj):
        return '✓' if obj.logo else '✗'
    has_logo.short_description = 'Логотип'
    
    def logo_preview(self, obj):
        if obj.logo:
            from django.utils.html import format_html
            return format_html('<img src="{}" style="max-height: 100px; max-width: 200px;" />', obj.logo.url)
        return "Логотип не загружен"
    logo_preview.short_description = 'Предпросмотр логотипа'
    
    def get_fields(self, request, obj=None):
        if obj and obj.logo:
            return ['insurer_name', 'logo', 'logo_preview', 'contacts', 'notes']
        return ['insurer_name', 'logo', 'contacts', 'notes']


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ['branch_name']
    search_fields = ['branch_name']


@admin.register(InsuranceType)
class InsuranceTypeAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(InfoTag)
class InfoTagAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(CommissionRate)
class CommissionRateAdmin(admin.ModelAdmin):
    list_display = ['insurer', 'insurance_type', 'kv_percent', 'created_at']
    list_filter = ['insurer', 'insurance_type']
    search_fields = ['insurer__insurer_name', 'insurance_type__name']
    autocomplete_fields = ['insurer', 'insurance_type']
