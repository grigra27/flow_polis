import logging
from datetime import timedelta
from email.utils import make_msgid

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.html import escape

from .models import (
    EmailDeliveryAttempt,
    MailAccount,
    OutboundEmail,
    OutboundEmailAttachment,
    OutboundEmailRecipient,
)
from .providers.smtp import SmtpEmailProvider
from .validators import validate_outbound_attachment

logger = logging.getLogger(__name__)


# Окно подавления дублирующих писем одного и того же типа на один объект.
RECENT_DUPLICATE_WINDOW = timedelta(seconds=60)


class CommunicationsError(Exception):
    """Base communications app error."""


class CommunicationsConfigurationError(CommunicationsError):
    """Raised when email sending is not configured."""


class CommunicationsQueueError(CommunicationsError):
    """Raised when a message cannot be queued for delivery."""


class CommunicationsSendError(CommunicationsError):
    """Raised when a provider fails to send an email."""


def get_default_mail_account():
    code = settings.COMMUNICATIONS_DEFAULT_ACCOUNT
    from_email = _settings_from_email()
    defaults = {
        "name": "Системный почтовый ящик",
        "email": from_email,
        "display_name": settings.COMMUNICATIONS_FROM_NAME,
        "provider": MailAccount.PROVIDER_SMTP,
        "is_active": True,
        "is_default": True,
        "settings_prefix": "COMMUNICATIONS",
    }
    account, created = MailAccount.objects.get_or_create(code=code, defaults=defaults)
    if created:
        return account

    changed_fields = []
    if from_email and account.email != from_email:
        account.email = from_email
        changed_fields.append("email")
    if (
        settings.COMMUNICATIONS_FROM_NAME
        and account.display_name != settings.COMMUNICATIONS_FROM_NAME
    ):
        account.display_name = settings.COMMUNICATIONS_FROM_NAME
        changed_fields.append("display_name")
    if changed_fields:
        account.save(update_fields=[*changed_fields, "updated_at"])
    return account


def create_outbound_email(
    *,
    kind,
    content_object,
    subject,
    body_text,
    body_html="",
    to,
    created_by=None,
    attachments=None,
):
    account = get_default_mail_account()
    content_type = ContentType.objects.get_for_model(
        content_object, for_concrete_model=False
    )
    _ensure_no_recent_duplicate(kind, content_type, content_object.pk)

    technical_code = build_technical_code(content_type, content_object.pk)
    message_id = build_message_id(technical_code)
    headers = build_headers(content_type, content_object.pk, kind, message_id)
    body_text = append_technical_code_to_text(body_text, technical_code)
    body_html = append_technical_code_to_html(body_html, technical_code)

    with transaction.atomic():
        outbound_email = OutboundEmail.objects.create(
            account=account,
            kind=kind,
            from_email=account.email,
            from_name=account.display_name,
            reply_to=account.email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            content_type=content_type,
            object_id=content_object.pk,
            created_by=created_by,
            message_id=message_id,
            headers=headers,
        )
        OutboundEmailRecipient.objects.create(
            email=outbound_email,
            recipient_type=OutboundEmailRecipient.TYPE_TO,
            address=to,
        )
        for uploaded_file in attachments or []:
            attach_uploaded_file(outbound_email, uploaded_file)
    return outbound_email


def attach_uploaded_file(outbound_email, uploaded_file):
    validation = validate_outbound_attachment(uploaded_file)
    attachment = OutboundEmailAttachment(
        email=outbound_email,
        original_filename=uploaded_file.name,
        content_type=validation.content_type,
        size=validation.size,
        checksum=validation.checksum,
    )
    attachment.file.save(validation.safe_filename, uploaded_file, save=False)
    attachment.save()
    return attachment


def queue_outbound_email(outbound_email, user=None):
    if not settings.COMMUNICATIONS_EMAIL_ENABLED:
        raise CommunicationsConfigurationError("Отправка писем временно отключена")
    _validate_smtp_settings()

    with transaction.atomic():
        email = (
            OutboundEmail.objects.select_for_update()
            .prefetch_related("recipients", "attachments")
            .get(pk=outbound_email.pk)
        )
        if email.status in {
            OutboundEmail.STATUS_QUEUED,
            OutboundEmail.STATUS_SENDING,
            OutboundEmail.STATUS_SENT,
        }:
            raise CommunicationsQueueError(
                "Письмо уже поставлено в очередь или отправлено"
            )
        if not email.recipients.filter(
            recipient_type=OutboundEmailRecipient.TYPE_TO
        ).exists():
            raise CommunicationsQueueError("Укажите получателя письма")
        if (
            email.kind == OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD
            and not email.attachments.exists()
        ):
            raise CommunicationsQueueError(
                "Для письма в Альянс необходимо приложить счет"
            )

        now = timezone.now()
        email.status = OutboundEmail.STATUS_QUEUED
        email.queued_at = now
        email.failed_at = None
        email.last_error = ""
        if user is not None:
            email.sent_by = user
        email.save(
            update_fields=[
                "status",
                "queued_at",
                "failed_at",
                "last_error",
                "sent_by",
                "updated_at",
            ]
        )
        transaction.on_commit(lambda email_id=email.id: _dispatch_send(email_id))

    return email


def retry_outbound_email(outbound_email, user=None):
    """Перевести failed-письмо обратно в очередь и заново разбудить worker."""
    if not settings.COMMUNICATIONS_EMAIL_ENABLED:
        raise CommunicationsConfigurationError("Отправка писем временно отключена")
    _validate_smtp_settings()

    with transaction.atomic():
        email = (
            OutboundEmail.objects.select_for_update()
            .prefetch_related("recipients", "attachments")
            .get(pk=outbound_email.pk)
        )
        if email.status != OutboundEmail.STATUS_FAILED:
            raise CommunicationsQueueError(
                "Повторная отправка возможна только для писем со статусом «Ошибка»"
            )
        if not email.recipients.filter(
            recipient_type=OutboundEmailRecipient.TYPE_TO
        ).exists():
            raise CommunicationsQueueError("Укажите получателя письма")
        if (
            email.kind == OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD
            and not email.attachments.exists()
        ):
            raise CommunicationsQueueError(
                "Для письма в Альянс необходимо приложить счет"
            )

        now = timezone.now()
        email.status = OutboundEmail.STATUS_QUEUED
        email.queued_at = now
        email.failed_at = None
        email.last_error = ""
        if user is not None:
            email.sent_by = user
        email.save(
            update_fields=[
                "status",
                "queued_at",
                "failed_at",
                "last_error",
                "sent_by",
                "updated_at",
            ]
        )
        transaction.on_commit(lambda email_id=email.id: _dispatch_send(email_id))

    return email


def _dispatch_send(email_id):
    """Поставить Celery-задачу. На ошибке брокера переводим письмо в failed."""
    try:
        from .tasks import send_outbound_email

        send_outbound_email.delay(email_id)
    except Exception as exc:
        logger.exception("Failed to enqueue outbound email %s", email_id)
        _mark_email_failed_after_enqueue(email_id, exc)


def _mark_email_failed_after_enqueue(email_id, exc):
    with transaction.atomic():
        try:
            failed_email = OutboundEmail.objects.select_for_update().get(pk=email_id)
        except OutboundEmail.DoesNotExist:
            return
        failed_email.status = OutboundEmail.STATUS_FAILED
        failed_email.failed_at = timezone.now()
        failed_email.last_error = f"Не удалось поставить письмо в очередь: {exc}"
        failed_email.save(
            update_fields=["status", "failed_at", "last_error", "updated_at"]
        )


def send_outbound_email_now(email_id):
    # PostgreSQL запрещает FOR UPDATE на nullable стороне OUTER JOIN.
    # У OutboundEmail поля created_by/sent_by — nullable, поэтому select_related
    # вместе с обычным select_for_update даёт NotSupportedError. of=("self",)
    # говорит «лочим только outboundemail», и джойны остаются вне локов.
    try:
        with transaction.atomic():
            email = (
                OutboundEmail.objects.select_for_update(of=("self",))
                .select_related("account", "created_by", "sent_by", "content_type")
                .prefetch_related("recipients", "attachments")
                .get(pk=email_id)
            )
            if email.status != OutboundEmail.STATUS_QUEUED:
                return f"skipped email {email.id} with status {email.status}"

            now = timezone.now()
            email.status = OutboundEmail.STATUS_SENDING
            email.sending_started_at = now
            email.save(update_fields=["status", "sending_started_at", "updated_at"])
            attempt = EmailDeliveryAttempt.objects.create(
                email=email,
                attempt_number=_next_attempt_number(email),
                status=EmailDeliveryAttempt.STATUS_SENDING,
                started_at=now,
            )
    except Exception as exc:
        # Любая ошибка до перехода в sending — оставила бы письмо в queued
        # навсегда. Помечаем его failed (без attempt'а, потому что он не создался),
        # чтобы UI-retry мог поднять.
        logger.exception("Failed to prepare outbound email %s for sending", email_id)
        _mark_email_failed_before_attempt(email_id, str(exc))
        raise CommunicationsSendError(str(exc)) from exc

    try:
        provider = get_provider(email.account)
        result = provider.send(email)
    except Exception as exc:
        logger.exception("Failed to send outbound email %s", email_id)
        _mark_email_failed(email_id, attempt.id, str(exc))
        raise CommunicationsSendError(str(exc)) from exc

    if not result.success:
        message = result.response or "Провайдер не подтвердил отправку письма"
        _mark_email_failed(email_id, attempt.id, message)
        raise CommunicationsSendError(message)

    with transaction.atomic():
        email = (
            OutboundEmail.objects.select_for_update(of=("self",))
            .select_related("account", "created_by", "sent_by", "content_type")
            .prefetch_related("recipients", "attachments")
            .get(pk=email_id)
        )
        now = timezone.now()
        email.status = OutboundEmail.STATUS_SENT
        email.sent_at = now
        email.failed_at = None
        email.last_error = ""
        if result.provider_message_id:
            email.provider_message_id = result.provider_message_id
        email.save(
            update_fields=[
                "status",
                "sent_at",
                "failed_at",
                "last_error",
                "provider_message_id",
                "updated_at",
            ]
        )
        attempt = EmailDeliveryAttempt.objects.select_for_update().get(pk=attempt.id)
        attempt.status = EmailDeliveryAttempt.STATUS_SENT
        attempt.finished_at = now
        attempt.provider_response = result.response
        attempt.save(
            update_fields=[
                "status",
                "finished_at",
                "provider_response",
                "updated_at",
            ]
        )

    handle_outbound_email_sent(email)
    return f"sent email {email.id}"


def get_provider(account):
    if account.provider == MailAccount.PROVIDER_SMTP:
        return SmtpEmailProvider()
    raise CommunicationsConfigurationError(
        f"Неизвестный почтовый провайдер: {account.provider}"
    )


def handle_outbound_email_sent(email):
    if email.kind in {
        OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD,
    }:
        from apps.billing.mail_handlers import handle_billing_email_sent

        handle_billing_email_sent(email)


def build_technical_code(content_type, object_id):
    app_label = content_type.app_label.upper()
    return f"OP-{app_label}-{object_id}"


def build_message_id(technical_code):
    domain = settings.COMMUNICATIONS_MESSAGE_ID_DOMAIN
    if not domain:
        from_email = _settings_from_email()
        domain = from_email.split("@", 1)[1] if "@" in from_email else "localhost"
    return make_msgid(idstring=technical_code.lower(), domain=domain)


def build_headers(content_type, object_id, kind, message_id):
    object_marker = f"{content_type.app_label}.{content_type.model}:{object_id}"
    return {
        "Message-ID": message_id,
        "X-Onlinepolis-Object": object_marker,
        "X-Onlinepolis-Email-Kind": kind,
    }


def append_technical_code_to_text(body_text, technical_code):
    return f"{body_text.rstrip()}\n\n---\nКод запроса: {technical_code}\n"


def append_technical_code_to_html(body_html, technical_code):
    if not body_html:
        return ""
    safe_code = escape(technical_code)
    return (
        f"{str(body_html).rstrip()}"
        f"<hr><p><small>Код запроса: {safe_code}</small></p>"
    )


def _ensure_no_recent_duplicate(kind, content_type, object_id):
    """Защита от двойного клика: один и тот же kind на тот же объект
    нельзя создать, если только что уже было поставлено письмо в работу."""
    threshold = timezone.now() - RECENT_DUPLICATE_WINDOW
    active_statuses = {
        OutboundEmail.STATUS_DRAFT,
        OutboundEmail.STATUS_QUEUED,
        OutboundEmail.STATUS_SENDING,
        OutboundEmail.STATUS_SENT,
    }
    recent = (
        OutboundEmail.objects.filter(
            kind=kind,
            content_type=content_type,
            object_id=object_id,
            status__in=active_statuses,
            created_at__gte=threshold,
        )
        .order_by("-created_at")
        .first()
    )
    if recent is not None:
        raise CommunicationsQueueError(
            "Аналогичное письмо только что уже было создано. "
            "Подождите минуту или откройте историю отправок."
        )


def _next_attempt_number(email):
    max_attempt = (
        EmailDeliveryAttempt.objects.filter(email=email).aggregate(
            max_attempt=Max("attempt_number")
        )["max_attempt"]
        or 0
    )
    return max_attempt + 1


def _mark_email_failed_before_attempt(email_id, error_message):
    """Перевести письмо в failed, когда EmailDeliveryAttempt ещё не создан.

    Срабатывает при ошибке на стадии select_for_update / select_related до того,
    как мы успели зафиксировать sending. Без этого письмо вечно висело бы в
    queued: queue_outbound_email не разрешает переотправку из queued.
    """
    try:
        with transaction.atomic():
            email = OutboundEmail.objects.select_for_update().get(pk=email_id)
            now = timezone.now()
            email.status = OutboundEmail.STATUS_FAILED
            email.failed_at = now
            email.last_error = error_message
            email.save(
                update_fields=["status", "failed_at", "last_error", "updated_at"]
            )
    except OutboundEmail.DoesNotExist:
        return
    except Exception:
        logger.exception("Failed to mark email %s as failed", email_id)


def _mark_email_failed(email_id, attempt_id, error_message):
    with transaction.atomic():
        email = OutboundEmail.objects.select_for_update().get(pk=email_id)
        now = timezone.now()
        email.status = OutboundEmail.STATUS_FAILED
        email.failed_at = now
        email.last_error = error_message
        email.save(update_fields=["status", "failed_at", "last_error", "updated_at"])

        attempt = EmailDeliveryAttempt.objects.select_for_update().get(pk=attempt_id)
        attempt.status = EmailDeliveryAttempt.STATUS_FAILED
        attempt.finished_at = now
        attempt.error_message = error_message
        attempt.save(
            update_fields=[
                "status",
                "finished_at",
                "error_message",
                "updated_at",
            ]
        )


def _settings_from_email():
    return (
        settings.COMMUNICATIONS_FROM_EMAIL
        or settings.COMMUNICATIONS_SMTP_USERNAME
        or "no-reply@localhost"
    )


def _validate_smtp_settings():
    missing = []
    if not settings.COMMUNICATIONS_SMTP_HOST:
        missing.append("COMMUNICATIONS_SMTP_HOST")
    if not settings.COMMUNICATIONS_SMTP_USERNAME:
        missing.append("COMMUNICATIONS_SMTP_USERNAME")
    if not settings.COMMUNICATIONS_SMTP_PASSWORD:
        missing.append("COMMUNICATIONS_SMTP_PASSWORD")
    if not _settings_from_email():
        missing.append("COMMUNICATIONS_FROM_EMAIL")
    if missing:
        raise CommunicationsConfigurationError(
            "Не настроена отправка писем: " + ", ".join(missing)
        )
