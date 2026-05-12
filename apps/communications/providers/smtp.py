import mimetypes
from email.header import Header
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from .base import BaseEmailProvider, SendResult
from apps.communications.models import OutboundEmailRecipient


class SmtpEmailProvider(BaseEmailProvider):
    def send(self, outbound_email):
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=settings.COMMUNICATIONS_SMTP_HOST,
            port=settings.COMMUNICATIONS_SMTP_PORT,
            username=settings.COMMUNICATIONS_SMTP_USERNAME,
            password=settings.COMMUNICATIONS_SMTP_PASSWORD,
            use_tls=settings.COMMUNICATIONS_SMTP_USE_TLS,
            use_ssl=settings.COMMUNICATIONS_SMTP_USE_SSL,
            timeout=settings.COMMUNICATIONS_SEND_TIMEOUT,
            fail_silently=False,
        )

        from_email = _format_sender(outbound_email.from_name, outbound_email.from_email)
        to = outbound_email.recipient_addresses(OutboundEmailRecipient.TYPE_TO)
        cc = outbound_email.recipient_addresses(OutboundEmailRecipient.TYPE_CC)
        bcc = outbound_email.recipient_addresses(OutboundEmailRecipient.TYPE_BCC)
        reply_to = [outbound_email.reply_to] if outbound_email.reply_to else None

        message = EmailMultiAlternatives(
            subject=outbound_email.subject,
            body=outbound_email.body_text,
            from_email=from_email,
            to=to,
            bcc=bcc,
            connection=connection,
            headers=outbound_email.headers,
            cc=cc,
            reply_to=reply_to,
        )
        if outbound_email.body_html:
            message.attach_alternative(outbound_email.body_html, "text/html")

        for attachment in outbound_email.attachments.all():
            content_type = attachment.content_type
            if not content_type:
                content_type, _ = mimetypes.guess_type(attachment.original_filename)
            with attachment.file.open("rb") as file_handle:
                message.attach(
                    attachment.original_filename,
                    file_handle.read(),
                    content_type or "application/octet-stream",
                )

        sent_count = message.send(fail_silently=False)
        return SendResult(
            success=sent_count > 0,
            provider_message_id=outbound_email.message_id,
            response=f"smtp sent count: {sent_count}",
        )


def _format_sender(name, email):
    if not name:
        return email
    return formataddr((str(Header(name, "utf-8")), email))
