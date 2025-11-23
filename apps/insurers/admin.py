from django.contrib import admin
from .models import Insurer, Branch, InsuranceType, InfoTag, CommissionRate


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = ['insurer_name', 'contacts']
    search_fields = ['insurer_name']
    fields = ['insurer_name', 'contacts', 'notes']


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
