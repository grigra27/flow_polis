from django.apps import AppConfig


class ClientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clients"
    verbose_name = "Клиенты"

    def ready(self):
        # Регистрация моделей для auditlog
        from auditlog.registry import auditlog
        from .models import Client

        auditlog.register(Client)
