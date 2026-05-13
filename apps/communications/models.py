from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class MailAccount(TimeStampedModel):
    """System mailbox used by the communications outbox."""

    PROVIDER_SMTP = "smtp"

    PROVIDER_CHOICES = [
        (PROVIDER_SMTP, "SMTP"),
    ]

    code = models.SlugField("Код", max_length=100, unique=True)
    name = models.CharField("Название", max_length=255)
    email = models.EmailField("Email")
    display_name = models.CharField("Отображаемое имя", max_length=255, blank=True)
    provider = models.CharField(
        "Провайдер",
        max_length=50,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_SMTP,
    )
    is_active = models.BooleanField("Активен", default=True)
    is_default = models.BooleanField("По умолчанию", default=False)
    settings_prefix = models.CharField(
        "Префикс настроек", max_length=100, default="COMMUNICATIONS"
    )

    class Meta:
        verbose_name = "Почтовый аккаунт"
        verbose_name_plural = "Почтовые аккаунты"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["is_default"]),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class OutboundEmailQuerySet(models.QuerySet):
    def for_object(self, obj):
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        return self.filter(content_type=content_type, object_id=obj.pk)


class OutboundEmail(TimeStampedModel):
    """Auditable outgoing email snapshot."""

    KIND_BILLING_INSURER_REQUEST = "billing_insurer_request"
    KIND_BILLING_ALLIANCE_FORWARD = "billing_alliance_forward"

    KIND_CHOICES = [
        (KIND_BILLING_INSURER_REQUEST, "Запрос счета в СК"),
        (KIND_BILLING_ALLIANCE_FORWARD, "Передача счета в Альянс"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_QUEUED = "queued"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_QUEUED, "В очереди"),
        (STATUS_SENDING, "Отправляется"),
        (STATUS_SENT, "Отправлено"),
        (STATUS_FAILED, "Ошибка"),
        (STATUS_CANCELLED, "Отменено"),
    ]

    account = models.ForeignKey(
        MailAccount,
        on_delete=models.PROTECT,
        verbose_name="Почтовый аккаунт",
        related_name="outbound_emails",
    )
    kind = models.CharField("Тип письма", max_length=80, choices=KIND_CHOICES)
    status = models.CharField(
        "Статус", max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )

    from_email = models.EmailField("Отправитель")
    from_name = models.CharField("Имя отправителя", max_length=255, blank=True)
    reply_to = models.EmailField("Reply-To", blank=True)

    subject = models.CharField("Тема", max_length=500)
    body_text = models.TextField("Текст")
    body_html = models.TextField("HTML", blank=True)

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name="Тип связанного объекта",
    )
    object_id = models.PositiveIntegerField("ID связанного объекта")
    content_object = GenericForeignKey("content_type", "object_id")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="Создал",
        related_name="created_outbound_emails",
        blank=True,
        null=True,
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="Отправил",
        related_name="sent_outbound_emails",
        blank=True,
        null=True,
    )

    queued_at = models.DateTimeField("Поставлено в очередь", blank=True, null=True)
    sending_started_at = models.DateTimeField(
        "Отправка началась", blank=True, null=True
    )
    sent_at = models.DateTimeField("Отправлено", blank=True, null=True)
    failed_at = models.DateTimeField("Ошибка отправки", blank=True, null=True)
    last_error = models.TextField("Последняя ошибка", blank=True)

    message_id = models.CharField("Message-ID", max_length=255, blank=True)
    provider_message_id = models.CharField(
        "ID письма у провайдера", max_length=255, blank=True
    )
    headers = models.JSONField("Служебные заголовки", default=dict, blank=True)

    objects = OutboundEmailQuerySet.as_manager()

    class Meta:
        verbose_name = "Исходящее письмо"
        verbose_name_plural = "Исходящие письма"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["sent_at"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["message_id"]),
        ]
        permissions = [
            ("send_outbound_email", "Может отправлять письма из системы"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.subject}"

    @property
    def is_terminal(self):
        return self.status in {
            self.STATUS_SENT,
            self.STATUS_CANCELLED,
        }

    def recipient_addresses(self, recipient_type=None):
        recipients = self.recipients.all()
        if recipient_type:
            recipients = recipients.filter(recipient_type=recipient_type)
        return [recipient.address for recipient in recipients]

    @property
    def to_addresses(self):
        """Список адресов TO без CC/BCC, в порядке добавления.
        Используется в задачной карточке: скрытая копия в историю
        не попадает, а пользователь видит адреса в том же порядке,
        как он их ввёл в форму."""
        recipients = sorted(self.recipients.all(), key=lambda r: r.id)
        return [r.address for r in recipients if r.recipient_type == "to"]


class OutboundEmailRecipient(TimeStampedModel):
    """Recipient snapshot for an outgoing email."""

    TYPE_TO = "to"
    TYPE_CC = "cc"
    TYPE_BCC = "bcc"

    TYPE_CHOICES = [
        (TYPE_TO, "Кому"),
        (TYPE_CC, "Копия"),
        (TYPE_BCC, "Скрытая копия"),
    ]

    email = models.ForeignKey(
        OutboundEmail,
        on_delete=models.CASCADE,
        verbose_name="Письмо",
        related_name="recipients",
    )
    recipient_type = models.CharField(
        "Тип получателя", max_length=10, choices=TYPE_CHOICES, default=TYPE_TO
    )
    address = models.EmailField("Email")
    name = models.CharField("Имя", max_length=255, blank=True)

    class Meta:
        verbose_name = "Получатель письма"
        verbose_name_plural = "Получатели писем"
        ordering = ["recipient_type", "address"]
        indexes = [
            models.Index(fields=["email", "recipient_type"]),
            models.Index(fields=["address"]),
        ]

    def __str__(self):
        return f"{self.get_recipient_type_display()}: {self.address}"


class OutboundEmailAttachment(TimeStampedModel):
    """File attached to an outgoing email."""

    email = models.ForeignKey(
        OutboundEmail,
        on_delete=models.CASCADE,
        verbose_name="Письмо",
        related_name="attachments",
    )
    file = models.FileField("Файл", upload_to="communications/outbound/%Y/%m/")
    original_filename = models.CharField("Исходное имя файла", max_length=255)
    content_type = models.CharField("MIME-тип", max_length=255, blank=True)
    size = models.PositiveIntegerField("Размер", default=0)
    checksum = models.CharField("SHA-256", max_length=64, blank=True)

    class Meta:
        verbose_name = "Вложение исходящего письма"
        verbose_name_plural = "Вложения исходящих писем"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["checksum"]),
        ]

    def __str__(self):
        return self.original_filename


class EmailDeliveryAttempt(TimeStampedModel):
    """One provider send attempt for an outgoing email."""

    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_SENDING, "Отправляется"),
        (STATUS_SENT, "Отправлено"),
        (STATUS_FAILED, "Ошибка"),
    ]

    email = models.ForeignKey(
        OutboundEmail,
        on_delete=models.CASCADE,
        verbose_name="Письмо",
        related_name="delivery_attempts",
    )
    attempt_number = models.PositiveSmallIntegerField("Номер попытки")
    status = models.CharField("Статус", max_length=30, choices=STATUS_CHOICES)
    started_at = models.DateTimeField("Начало", blank=True, null=True)
    finished_at = models.DateTimeField("Завершение", blank=True, null=True)
    error_message = models.TextField("Ошибка", blank=True)
    provider_response = models.TextField("Ответ провайдера", blank=True)

    class Meta:
        verbose_name = "Попытка отправки письма"
        verbose_name_plural = "Попытки отправки писем"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["email", "attempt_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.email_id} — попытка {self.attempt_number}"
