from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        # Регистрация моделей для auditlog
        from auditlog.registry import auditlog
        from .models import LoginAttempt
        from django.contrib.auth.models import User

        auditlog.register(LoginAttempt)
        auditlog.register(User)  # Отслеживаем изменения пользователей
