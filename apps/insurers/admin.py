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
    list_display = ['branch_name', 'has_logo']
    search_fields = ['branch_name']
    fields = ['branch_name', 'logo']
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
            return ['branch_name', 'logo', 'logo_preview']
        return ['branch_name', 'logo']


@admin.register(InsuranceType)
class InsuranceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'has_icon']
    search_fields = ['name']
    fields = ['name', 'icon']
    readonly_fields = ['icon_preview']
    
    def has_icon(self, obj):
        return '✓' if obj.icon else '✗'
    has_icon.short_description = 'Иконка'
    
    def icon_preview(self, obj):
        if obj.icon:
            from django.utils.html import format_html
            return format_html('<img src="{}" style="max-height: 100px; max-width: 200px;" />', obj.icon.url)
        return "Иконка не загружена"
    icon_preview.short_description = 'Предпросмотр иконки'
    
    def get_fields(self, request, obj=None):
        if obj and obj.icon:
            return ['name', 'icon', 'icon_preview']
        return ['name', 'icon']


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
