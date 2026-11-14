from django.contrib import admin
from django import forms
from django.conf import settings
from django.utils import timezone
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


class CommissionRateForm(forms.ModelForm):
    class Meta:
        model = CommissionRate
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and "effective_from" in self.fields:
            self.fields["effective_from"].required = True
            self.fields[
                "effective_from"
            ].help_text = "Включительно. Ставка подбирается для вновь добавляемых полисов по дате начала страхования."


@admin.register(CommissionRate)
class CommissionRateAdmin(admin.ModelAdmin):
    change_form_template = "admin/insurers/commissionrate/change_form.html"
    form = CommissionRateForm
    list_display = [
        "insurer",
        "insurance_type",
        "kv_percent_display",
        "effective_from",
        "selection_status",
        "notes",
    ]
    list_filter = ["insurer", "insurance_type"]
    search_fields = ["insurer__insurer_name", "insurance_type__name"]
    autocomplete_fields = ["insurer", "insurance_type"]
    fields = ["insurer", "insurance_type", "kv_percent", "effective_from", "notes"]
    date_hierarchy = "effective_from"
    ordering = ["insurer", "insurance_type", "-effective_from"]

    class Media:
        js = (
            f"{settings.STATIC_URL}insurers/js/commission_rate_form.js?v=2026-11-14.2",
        )

    def get_readonly_fields(self, request, obj=None):
        return (
            ["insurer", "insurance_type", "kv_percent", "effective_from"]
            if obj and obj.is_used
            else []
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.is_used)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("insurer", "insurance_type")

    @admin.display(description="Подбор новых полисов")
    def selection_status(self, obj):
        today = timezone.localdate()
        if obj.effective_from and obj.effective_from > today:
            return "Запланирована"
        current = CommissionRate.objects.for_policy(
            obj.insurer_id, obj.insurance_type_id, today
        ).first()
        return "Текущая" if current and current.pk == obj.pk else "Предыдущие условия"

    def kv_percent_display(self, obj):
        """Отображение КВ без дробной части"""
        return f"{obj.kv_percent.normalize():f}%"

    kv_percent_display.short_description = "КВ %"
    kv_percent_display.admin_order_field = "kv_percent"
