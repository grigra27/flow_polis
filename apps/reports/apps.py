from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    verbose_name = "Отчеты"

    def ready(self):
        # Регистрация моделей для auditlog
        from auditlog.registry import auditlog
        from .models import CustomExportTemplate

        auditlog.register(CustomExportTemplate)
