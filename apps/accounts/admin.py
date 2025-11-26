from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html


# Unregister the default User admin
admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """
    Кастомная конфигурация админки для модели User
    с фокусом на управление типами пользователей (обычный/администратор)
    """
    
    list_display = [
        'username', 'email', 'first_name', 'last_name',
        'user_type_display', 'is_active', 'last_login', 'date_joined'
    ]
    
    list_filter = [
        'is_staff', 'is_superuser', 'is_active',
        'date_joined', 'last_login'
    ]
    
    search_fields = ['username', 'first_name', 'last_name', 'email']
    
    ordering = ['-date_joined']
    
    # Настройка полей для формы редактирования
    fieldsets = (
        ('Основная информация', {
            'fields': ('username', 'password')
        }),
        ('Персональные данные', {
            'fields': ('first_name', 'last_name', 'email')
        }),
        ('Права доступа', {
            'fields': ('is_active', 'is_staff', 'is_superuser'),
            'description': 'is_staff=True для администратора, is_staff=False для обычного пользователя'
        }),
        ('Важные даты', {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
    )
    
    # Настройка полей для формы создания нового пользователя
    add_fieldsets = (
        ('Учетные данные', {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
        ('Персональные данные', {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'email'),
        }),
        ('Тип пользователя', {
            'classes': ('wide',),
            'fields': ('is_staff', 'is_superuser'),
            'description': (
                'Обычный пользователь: is_staff=False, is_superuser=False (только просмотр и экспорт)\n'
                'Администратор: is_staff=True, is_superuser=True (полный доступ)'
            )
        }),
    )
    
    readonly_fields = ['last_login', 'date_joined']
    
    def user_type_display(self, obj):
        """
        Отображение типа пользователя с цветовой индикацией
        """
        if obj.is_superuser and obj.is_staff:
            return format_html(
                '<span style="color: #0066cc; font-weight: bold;">👑 Администратор</span>'
            )
        elif obj.is_staff:
            return format_html(
                '<span style="color: #0066cc;">🔧 Администратор</span>'
            )
        else:
            return format_html(
                '<span style="color: #666;">👤 Обычный пользователь</span>'
            )
    
    user_type_display.short_description = 'Тип пользователя'
    user_type_display.admin_order_field = 'is_staff'
    
    def save_model(self, request, obj, form, change):
        """
        Переопределение сохранения для обеспечения корректной установки прав
        """
        # Если создается новый пользователь и установлен is_staff,
        # автоматически устанавливаем is_superuser для полного доступа к админке
        if not change and obj.is_staff and not obj.is_superuser:
            obj.is_superuser = True
        
        super().save_model(request, obj, form, change)
