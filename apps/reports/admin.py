from django.contrib import admin
from .models import CustomExportTemplate


@admin.register(CustomExportTemplate)
class CustomExportTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "data_source", "created_at"]
    list_filter = ["data_source", "created_at"]
    search_fields = ["name", "user__username"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Основная информация", {"fields": ("user", "name", "data_source")}),
        ("Конфигурация", {"fields": ("config",)}),
        (
            "Системная информация",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
