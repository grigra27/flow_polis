from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    verbose_name = "Выставление счетов"

    def ready(self):
        from auditlog.registry import auditlog

        from . import signals  # noqa: F401
        from .models import BillingPeriod, BillingTask, BillingTaskEvent

        auditlog.register(BillingPeriod)
        auditlog.register(BillingTask)
        auditlog.register(BillingTaskEvent)
