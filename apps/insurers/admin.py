from django.contrib import admin
from .models import (
    Insurer,
    Branch,
    InsuranceType,
    InfoTag,
    CommissionRate,
    LeasingManager,
)


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = [
        "insurer_name",
        "contacts",
        "email_primary",
        "email_secondary",
        "has_logo",
    ]
    search_fields = ["insurer_name", "email_primary", "email_secondary"]
    fields = [
        "insurer_name",
        "logo",
        "contacts",
        "email_primary",
        "email_secondary",
        "notes",
    ]
    readonly_fields = ["logo_preview"]

    def has_logo(self, obj):
        return "✓" if obj.logo else "✗"

    has_logo.short_description = "Логотип"

    def logo_preview(self, obj):
        if obj.logo:
            from django.utils.html import format_html

            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 200px;" />',
                obj.logo.url,
            )
        return "Логотип не загружен"

    logo_preview.short_description = "Предпросмотр логотипа"

    def get_fields(self, request, obj=None):
        if obj and obj.logo:
            return [
                "insurer_name",
                "logo",
                "logo_preview",
                "contacts",
                "email_primary",
                "email_secondary",
                "notes",
            ]
        return [
            "insurer_name",
            "logo",
            "contacts",
            "email_primary",
            "email_secondary",
            "notes",
        ]


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["branch_name", "has_logo"]
    search_fields = ["branch_name"]
    fields = ["branch_name", "logo"]
    readonly_fields = ["logo_preview"]

    def has_logo(self, obj):
        return "✓" if obj.logo else "✗"

    has_logo.short_description = "Логотип"

    def logo_preview(self, obj):
        if obj.logo:
            from django.utils.html import format_html

            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 200px;" />',
                obj.logo.url,
            )
        return "Логотип не загружен"

    logo_preview.short_description = "Предпросмотр логотипа"

    def get_fields(self, request, obj=None):
        if obj and obj.logo:
            return ["branch_name", "logo", "logo_preview", "latitude", "longitude"]
        return ["branch_name", "logo", "latitude", "longitude"]


@admin.register(InsuranceType)
class InsuranceTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "is_osago", "needs_prolongation", "has_icon"]
    search_fields = ["name"]
    # is_osago не редактируется: признак ставит миграция insurers.0014,
    # смена у вида с полисами сломала бы правила их платежей.
    fields = ["name", "needs_prolongation", "icon"]
    readonly_fields = ["icon_preview"]

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(
            request, queryset, search_term
        )
        # Автодополнение «Вид страхования» в разделе «Полисы»: ОСАГО
        # заводится только в разделе «Полисы ОСАГО».
        if (
            request.GET.get("app_label") == "policies"
            and request.GET.get("model_name") == "policy"
            and request.GET.get("field_name") == "insurance_type"
        ):
            queryset = queryset.filter(is_osago=False)
        return queryset, may_have_duplicates

    def has_icon(self, obj):
        return "✓" if obj.icon else "✗"

    has_icon.short_description = "Иконка"

    def icon_preview(self, obj):
        if obj.icon:
            from django.utils.html import format_html

            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 200px;" />',
                obj.icon.url,
            )
        return "Иконка не загружена"

    icon_preview.short_description = "Предпросмотр иконки"

    def get_fields(self, request, obj=None):
        if obj and obj.icon:
            return ["name", "icon", "icon_preview"]
        return ["name", "icon"]


@admin.register(InfoTag)
class InfoTagAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(LeasingManager)
class LeasingManagerAdmin(admin.ModelAdmin):
    list_display = ["name", "full_name", "branch", "phone", "email"]
    list_filter = ["branch"]
    search_fields = ["name", "full_name", "phone", "email", "branch__branch_name"]
    fields = ["name", "full_name", "branch", "phone", "email", "notes"]
    autocomplete_fields = ["branch"]
    ordering = ["name"]


@admin.register(CommissionRate)
class CommissionRateAdmin(admin.ModelAdmin):
    list_display = ["insurer", "insurance_type", "kv_percent_display", "created_at"]
    list_filter = ["insurer", "insurance_type"]
    search_fields = ["insurer__insurer_name", "insurance_type__name"]
    autocomplete_fields = ["insurer", "insurance_type"]

    def kv_percent_display(self, obj):
        """Отображение КВ без дробной части"""
        return f"{int(round(float(obj.kv_percent)))}%"

    kv_percent_display.short_description = "КВ %"
    kv_percent_display.admin_order_field = "kv_percent"
