from django.contrib import admin
from django.utils.html import format_html
from auditlog.models import LogEntry
from auditlog.admin import LogEntryAdmin


# Отменяем регистрацию стандартной админки auditlog
admin.site.unregister(LogEntry)


@admin.register(LogEntry)
class CustomLogEntryAdmin(LogEntryAdmin):
    """
    Кастомная админка для записей аудита с улучшенным отображением
    """

    list_display = [
        "timestamp_display",
        "action_display",
        "content_type",
        "object_repr_short",
        "actor_display",
        "remote_addr",
    ]

    list_filter = [
        "action",
        "content_type",
        "timestamp",
    ]

    search_fields = [
        "object_repr",
        "actor__username",
        "remote_addr",
    ]

    readonly_fields = [
        "timestamp",
        "content_type",
        "object_pk",
        "object_id",
        "object_repr",
        "action",
        "changes_display",
        "actor",
        "remote_addr",
        "additional_data",
    ]

    fieldsets = (
        (
            "Основная информация",
            {
                "fields": (
                    "timestamp",
                    "action",
                    "content_type",
                    "object_repr",
                    "actor",
                    "remote_addr",
                )
            },
        ),
        (
            "Детали изменений",
            {"fields": ("changes_display",), "classes": ("collapse",)},
        ),
        (
            "Техническая информация",
            {
                "fields": (
                    "object_pk",
                    "object_id",
                    "additional_data",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    date_hierarchy = "timestamp"
    ordering = ["-timestamp"]

    def timestamp_display(self, obj):
        """Отображение времени в удобном формате в часовом поясе Дохи"""
        from django.utils import timezone
        from zoneinfo import ZoneInfo

        # Конвертируем время в часовой пояс Дохи, Катар (UTC+3)
        qatar_tz = ZoneInfo("Asia/Qatar")
        local_time = obj.timestamp.astimezone(qatar_tz)

        return local_time.strftime("%d.%m.%Y %H:%M:%S")

    timestamp_display.short_description = "Время (Доха)"
    timestamp_display.admin_order_field = "timestamp"

    def action_display(self, obj):
        """Отображение действия с цветовой индикацией"""
        action_colors = {
            0: ("green", "✓ Создание"),  # CREATE
            1: ("orange", "✎ Изменение"),  # UPDATE
            2: ("red", "✗ Удаление"),  # DELETE
        }

        color, text = action_colors.get(obj.action, ("gray", "Неизвестно"))
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>', color, text
        )

    action_display.short_description = "Действие"
    action_display.admin_order_field = "action"

    def object_repr_short(self, obj):
        """Сокращенное представление объекта"""
        if len(obj.object_repr) > 50:
            return obj.object_repr[:50] + "..."
        return obj.object_repr

    object_repr_short.short_description = "Объект"

    def actor_display(self, obj):
        """Отображение пользователя"""
        if obj.actor:
            return format_html(
                '<span title="{}">{}</span>',
                f"ID: {obj.actor.id}, Email: {obj.actor.email}",
                obj.actor.username,
            )
        return format_html('<span style="color: gray;">Система</span>')

    actor_display.short_description = "Пользователь"

    def changes_display(self, obj):
        """Красивое отображение изменений"""
        if not obj.changes:
            return "Нет изменений"

        import json

        try:
            changes = (
                json.loads(obj.changes) if isinstance(obj.changes, str) else obj.changes
            )
            html_parts = []

            for field, (old_val, new_val) in changes.items():
                # Пропускаем служебные поля
                if field in ["id", "password", "last_login"]:
                    continue

                # Форматируем значения
                old_display = str(old_val) if old_val is not None else "Пусто"
                new_display = str(new_val) if new_val is not None else "Пусто"

                # Обрезаем длинные значения
                if len(old_display) > 100:
                    old_display = old_display[:100] + "..."
                if len(new_display) > 100:
                    new_display = new_display[:100] + "..."

                html_parts.append(
                    f'<div style="margin-bottom: 8px;">'
                    f"<strong>{field}:</strong><br>"
                    f'<span style="color: red;">- {old_display}</span><br>'
                    f'<span style="color: green;">+ {new_display}</span>'
                    f"</div>"
                )

            return format_html("".join(html_parts))

        except (json.JSONDecodeError, TypeError, ValueError):
            return obj.changes

    changes_display.short_description = "Изменения"

    def has_add_permission(self, request):
        """Запрещаем создание записей аудита вручную"""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещаем редактирование записей аудита"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрещаем удаление записей аудита"""
        return False
