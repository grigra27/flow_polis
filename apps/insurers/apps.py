from django.apps import AppConfig


class InsurersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.insurers"
    verbose_name = "Справочники"

    def ready(self):
        # Регистрация моделей для auditlog
        from auditlog.registry import auditlog
        from .models import (
            Insurer,
            Branch,
            InsuranceType,
            InfoTag,
            CommissionRate,
            LeasingManager,
        )

        auditlog.register(Insurer)
        auditlog.register(Branch)
        auditlog.register(InsuranceType)
        auditlog.register(InfoTag)
        auditlog.register(CommissionRate)
        auditlog.register(LeasingManager)
