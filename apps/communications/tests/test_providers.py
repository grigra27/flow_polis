from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.test import override_settings

from apps.billing.models import BillingPeriod, BillingTask
from apps.communications.models import (
    MailAccount,
    OutboundEmail,
    OutboundEmailAttachment,
    OutboundEmailRecipient,
)
from apps.communications.providers.smtp import SmtpEmailProvider


@pytest.fixture
def mail_account(db):
    return MailAccount.objects.create(
        code="billing",
        name="Тестовый ящик",
        email="sender@example.com",
        display_name="ОнлайнПолис",
        provider=MailAccount.PROVIDER_SMTP,
        is_active=True,
        is_default=True,
    )


@pytest.fixture
def outbound_email(db, mail_account):
    # BillingTask нужен только как content_object — фикстуру тут не плодим:
    # достаточно любого ContentType для теста провайдера, но для генерик-FK
    # содержательный объект нужен. Используем BillingPeriod как самый простой.
    period = BillingPeriod.objects.create(year=2026, month=5)
    content_type = ContentType.objects.get_for_model(period)
    email = OutboundEmail.objects.create(
        account=mail_account,
        kind=OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        from_email="sender@example.com",
        from_name="ОнлайнПолис",
        reply_to="sender@example.com",
        subject="Тестовая тема",
        body_text="Тело письма",
        body_html="<p>Тело письма</p>",
        content_type=content_type,
        object_id=period.pk,
        message_id="<test@onlinepolis.local>",
        headers={
            "Message-ID": "<test@onlinepolis.local>",
            "X-Onlinepolis-Object": "billing.billingperiod:1",
            "X-Onlinepolis-Email-Kind": OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        },
        status=OutboundEmail.STATUS_QUEUED,
    )
    OutboundEmailRecipient.objects.create(
        email=email,
        recipient_type=OutboundEmailRecipient.TYPE_TO,
        address="recipient@example.com",
    )
    OutboundEmailRecipient.objects.create(
        email=email,
        recipient_type=OutboundEmailRecipient.TYPE_CC,
        address="cc@example.com",
    )
    attachment = OutboundEmailAttachment(
        email=email,
        original_filename="invoice.pdf",
        content_type="application/pdf",
        size=10,
        checksum="x" * 64,
    )
    attachment.file.save("invoice.pdf", ContentFile(b"%PDF-1.4\nbody"), save=True)
    return email


@override_settings(
    COMMUNICATIONS_SMTP_HOST="smtp.example.com",
    COMMUNICATIONS_SMTP_PORT=465,
    COMMUNICATIONS_SMTP_USERNAME="sender@example.com",
    COMMUNICATIONS_SMTP_PASSWORD="not-a-real-password",  # pragma: allowlist secret
    COMMUNICATIONS_SMTP_USE_TLS=False,
    COMMUNICATIONS_SMTP_USE_SSL=True,
    COMMUNICATIONS_SEND_TIMEOUT=15,
)
@pytest.mark.django_db
def test_smtp_provider_sends_message_with_recipients_headers_html_attachment(
    outbound_email,
):
    captured = {}

    class FakeConnection:
        def open(self):
            return None

        def close(self):
            return None

    def fake_get_connection(*args, **kwargs):
        return FakeConnection()

    def fake_send(self, fail_silently=False):
        captured["to"] = list(self.to)
        captured["cc"] = list(self.cc)
        captured["bcc"] = list(self.bcc)
        captured["reply_to"] = list(self.reply_to)
        captured["subject"] = self.subject
        captured["body"] = self.body
        captured["from_email"] = self.from_email
        captured["headers"] = dict(self.extra_headers)
        captured["alternatives"] = [
            (content, mimetype) for content, mimetype in self.alternatives
        ]
        captured["attachments"] = [
            (filename, content, mimetype)
            for filename, content, mimetype in self.attachments
        ]
        return 1

    with patch(
        "apps.communications.providers.smtp.get_connection", fake_get_connection
    ), patch(
        "django.core.mail.message.EmailMultiAlternatives.send",
        fake_send,
        create=False,
    ):
        result = SmtpEmailProvider().send(outbound_email)

    assert result.success is True
    assert result.provider_message_id == ""  # SMTP backend не возвращает ID сервера
    assert captured["to"] == ["recipient@example.com"]
    assert captured["cc"] == ["cc@example.com"]
    assert captured["subject"] == "Тестовая тема"
    assert captured["body"] == "Тело письма"
    assert "sender@example.com" in captured["from_email"]
    assert captured["headers"]["Message-ID"] == "<test@onlinepolis.local>"
    assert (
        captured["headers"]["X-Onlinepolis-Email-Kind"]
        == OutboundEmail.KIND_BILLING_INSURER_REQUEST
    )
    html_alternatives = [
        alt for alt in captured["alternatives"] if alt[1] == "text/html"
    ]
    assert html_alternatives and "Тело письма" in html_alternatives[0][0]
    assert captured["attachments"]
    filename, content, mimetype = captured["attachments"][0]
    assert filename == "invoice.pdf"
    assert b"%PDF" in content
    assert mimetype == "application/pdf"
