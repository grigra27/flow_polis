from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from .models import LoginAttempt


# Unregister the default User admin
admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """
    Кастомная конфигурация админки для модели User
    с фокусом на управление типами пользователей (обычный/администратор)
    """

    list_display = [
        "username",
        "email",
        "first_name",
        "last_name",
        "user_type_display",
        "is_active",
        "last_login",
        "date_joined",
    ]

    list_filter = ["is_staff", "is_superuser", "is_active", "date_joined", "last_login"]

    search_fields = ["username", "first_name", "last_name", "email"]

    ordering = ["-date_joined"]

    # Настройка полей для формы редактирования
    fieldsets = (
        ("Основная информация", {"fields": ("username", "password")}),
        ("Персональные данные", {"fields": ("first_name", "last_name", "email")}),
        (
            "Права доступа",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "description": (
                    "is_staff=True - доступ к админ-панели\n"
                    "is_superuser=True - полный доступ ко всему\n"
                    "Для гранулярных прав: is_staff=True, is_superuser=False, затем выберите конкретные права ниже"
                ),
            },
        ),
        (
            "Важные даты",
            {"fields": ("last_login", "date_joined"), "classes": ("collapse",)},
        ),
    )

    # Настройка полей для формы создания нового пользователя
    add_fieldsets = (
        (
            "Учетные данные",
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
        (
            "Персональные данные",
            {
                "classes": ("wide",),
                "fields": ("first_name", "last_name", "email"),
            },
        ),
        (
            "Тип пользователя",
            {
                "classes": ("wide",),
                "fields": ("is_staff", "is_superuser", "groups", "user_permissions"),
                "description": (
                    "Обычный пользователь: is_staff=False, is_superuser=False (только просмотр и экспорт)\n"
                    "Администратор с полным доступом: is_staff=True, is_superuser=True\n"
                    "Администратор с ограниченными правами: is_staff=True, is_superuser=False + выберите конкретные права"
                ),
            },
        ),
    )

    readonly_fields = ["last_login", "date_joined"]

    def user_type_display(self, obj):
        """
        Отображение типа пользователя с цветовой индикацией
        """
        if obj.is_superuser and obj.is_staff:
            return format_html(
                '<span style="color: #0066cc; font-weight: bold;">👑 Администратор</span>'
            )
        elif obj.is_staff:
            return format_html('<span style="color: #0066cc;">🔧 Администратор</span>')
        else:
            return format_html(
                '<span style="color: #666;">👤 Обычный пользователь</span>'
            )

    user_type_display.short_description = "Тип пользователя"
    user_type_display.admin_order_field = "is_staff"

    def save_model(self, request, obj, form, change):
        """
        Переопределение сохранения для обеспечения корректной установки прав
        """
        # Больше не устанавливаем автоматически is_superuser
        # Теперь суперюзер может создавать пользователей с гранулярными правами
        super().save_model(request, obj, form, change)


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """
    Admin interface for LoginAttempt model.

    Allows administrators to view login attempts and identify
    potential security threats.
    """

    list_display = [
        "username",
        "ip_address",
        "attempt_time",
        "success_display",
        "user_agent_short",
    ]

    list_filter = ["success", "attempt_time"]

    search_fields = ["username", "ip_address", "user_agent"]

    readonly_fields = [
        "ip_address",
        "username",
        "attempt_time",
        "success",
        "user_agent",
    ]

    ordering = ["-attempt_time"]

    date_hierarchy = "attempt_time"

    def success_display(self, obj):
        """Display success status with color coding"""
        if obj.success:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Успешная</span>'
            )
        else:
            return format_html(
                '<span style="color: red; font-weight: bold;">✗ Неудачная</span>'
            )

    success_display.short_description = "Статус"
    success_display.admin_order_field = "success"

    def user_agent_short(self, obj):
        """Display shortened user agent"""
        if len(obj.user_agent) > 50:
            return obj.user_agent[:50] + "..."
        return obj.user_agent

    user_agent_short.short_description = "User Agent"

    def has_add_permission(self, request):
        """Disable manual creation of login attempts"""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable editing of login attempts"""
        return False
