from django.apps import AppConfig


class PoliciesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.policies"
    verbose_name = "Полисы"

    def ready(self):
        import apps.policies.signals

        # Регистрация моделей для auditlog
        from auditlog.registry import auditlog
        from .models import Policy, PaymentSchedule, PolicyInfo

        auditlog.register(Policy)
        auditlog.register(PaymentSchedule)
        auditlog.register(PolicyInfo)
