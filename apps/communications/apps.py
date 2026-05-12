from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.communications"
    verbose_name = "Коммуникации"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import (
            EmailDeliveryAttempt,
            MailAccount,
            OutboundEmail,
            OutboundEmailAttachment,
            OutboundEmailRecipient,
        )

        auditlog.register(MailAccount)
        auditlog.register(OutboundEmail)
        auditlog.register(OutboundEmailRecipient)
        auditlog.register(OutboundEmailAttachment)
        auditlog.register(EmailDeliveryAttempt)
