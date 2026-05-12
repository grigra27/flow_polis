from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.communications"
    verbose_name = "Коммуникации"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import MailAccount, OutboundEmail

        # Регистрируем только корневые сущности. Получателей, вложения и
        # попытки отправки писать в auditlog не имеет смысла — их история
        # уже хранится в самих моделях, а daily_digest читает auditlog
        # и не должен заваливаться техническими событиями.
        auditlog.register(MailAccount)
        auditlog.register(
            OutboundEmail,
            exclude_fields=[
                "queued_at",
                "sending_started_at",
                "sent_at",
                "failed_at",
                "last_error",
                "provider_message_id",
                "headers",
                "body_text",
                "body_html",
            ],
        )
