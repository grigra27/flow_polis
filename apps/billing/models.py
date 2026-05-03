import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.policies.models import PaymentSchedule


class BillingPeriod(TimeStampedModel):
    """Месячный рабочий период для очередных взносов."""

    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Активен"),
        (STATUS_ARCHIVED, "Архив"),
    ]

    year = models.PositiveSmallIntegerField("Год")
    month = models.PositiveSmallIntegerField("Месяц")
    status = models.CharField(
        "Статус периода",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )

    class Meta:
        verbose_name = "Период очередных взносов"
        verbose_name_plural = "Периоды очередных взносов"
        unique_together = ["year", "month"]
        ordering = ["year", "month"]
        indexes = [
            models.Index(fields=["year", "month"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return self.label

    @property
    def starts_on(self):
        return date(self.year, self.month, 1)

    @property
    def ends_on(self):
        _, last_day = calendar.monthrange(self.year, self.month)
        return date(self.year, self.month, last_day)

    @property
    def label(self):
        month_names = {
            1: "Январь",
            2: "Февраль",
            3: "Март",
            4: "Апрель",
            5: "Май",
            6: "Июнь",
            7: "Июль",
            8: "Август",
            9: "Сентябрь",
            10: "Октябрь",
            11: "Ноябрь",
            12: "Декабрь",
        }
        return f"{month_names.get(self.month, self.month)} {self.year}"

    @property
    def code(self):
        return f"{self.year:04d}-{self.month:02d}"


class BillingTask(TimeStampedModel):
    """Рабочая задача по запросу счета для одного очередного взноса."""

    STATUS_TO_REQUEST = "to_request"
    STATUS_REQUESTED = "requested"
    STATUS_SENT_TO_LEASING = "sent_to_leasing"

    STATUS_CHOICES = [
        (STATUS_TO_REQUEST, "Требуется запрос"),
        (STATUS_REQUESTED, "Счет запрошен у СК"),
        (STATUS_SENT_TO_LEASING, "Передан в оплату в Альянс"),
    ]

    period = models.ForeignKey(
        BillingPeriod,
        on_delete=models.CASCADE,
        verbose_name="Период",
        related_name="tasks",
    )
    payment_schedule = models.OneToOneField(
        PaymentSchedule,
        on_delete=models.CASCADE,
        verbose_name="Платеж",
        related_name="billing_task",
    )
    status = models.CharField(
        "Статус",
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_TO_REQUEST,
        db_index=True,
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="Ответственный",
        related_name="billing_tasks",
        blank=True,
        null=True,
    )
    invoice_request_deadline = models.DateField("Крайняя дата запроса счета")
    requested_at = models.DateTimeField("Счет запрошен", blank=True, null=True)
    sent_to_leasing_at = models.DateTimeField(
        "Передан в лизинговую", blank=True, null=True
    )
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Задача по очередному взносу"
        verbose_name_plural = "Задачи по очередным взносам"
        ordering = ["invoice_request_deadline", "payment_schedule__due_date", "id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["invoice_request_deadline"]),
            models.Index(fields=["requested_at"]),
            models.Index(fields=["sent_to_leasing_at"]),
            models.Index(fields=["period", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.payment_schedule.policy.policy_number} - "
            f"{self.get_status_display()}"
        )

    def get_absolute_url(self):
        return reverse("policies:scheduled_payment_task", kwargs={"pk": self.pk})

    @property
    def policy(self):
        return self.payment_schedule.policy

    @property
    def amount(self):
        return self.payment_schedule.amount

    @property
    def due_date(self):
        return self.payment_schedule.due_date

    @property
    def is_actual(self):
        payment = self.payment_schedule
        return (
            payment.paid_date is None
            and payment.policy.policy_active
            and self.period.starts_on <= payment.due_date <= self.period.ends_on
        )

    def build_letter_text(self):
        policy = self.policy

        lines = [
            "Добрый день.",
            "",
            "Просим выставить счет на очередной взнос по договору страхования:",
            "",
            f"Страховщик: {policy.insurer.insurer_name}",
            "Страхователь: "
            f"{policy.policyholder.client_name if policy.policyholder else ''}",
            f"Лизингополучатель: {policy.client.client_name}",
            f"Номер ДФА: {policy.dfa_number or ''}",
            f"Номер полиса: {policy.policy_number}",
            f"Объект страхования: {policy.property_description}",
            f"Дата платежа по договору: {self.due_date.strftime('%d.%m.%Y')}",
            f"Сумма очередного взноса: {format_money(self.amount)}",
        ]

        lines.extend(
            [
                "",
                "Просим направить счет для дальнейшей передачи в оплату клиенту.",
                "",
                "Спасибо.",
            ]
        )
        return "\n".join(lines)


class BillingTaskEvent(TimeStampedModel):
    """История действий по задаче очередного взноса."""

    EVENT_CREATED = "created"
    EVENT_STATUS_CHANGED = "status_changed"
    EVENT_SYNCED = "synced"

    EVENT_CHOICES = [
        (EVENT_CREATED, "Создана"),
        (EVENT_STATUS_CHANGED, "Изменен статус"),
        (EVENT_SYNCED, "Синхронизирована"),
    ]

    task = models.ForeignKey(
        BillingTask,
        on_delete=models.CASCADE,
        verbose_name="Задача",
        related_name="events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="Пользователь",
        blank=True,
        null=True,
    )
    event_type = models.CharField("Тип события", max_length=30, choices=EVENT_CHOICES)
    old_status = models.CharField("Предыдущий статус", max_length=30, blank=True)
    new_status = models.CharField("Новый статус", max_length=30, blank=True)
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Событие задачи очередного взноса"
        verbose_name_plural = "События задач очередных взносов"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.task_id} - {self.get_event_type_display()}"

    @property
    def old_status_label(self):
        return dict(BillingTask.STATUS_CHOICES).get(self.old_status, self.old_status)

    @property
    def new_status_label(self):
        return dict(BillingTask.STATUS_CHOICES).get(self.new_status, self.new_status)


def format_money(value):
    if value is None:
        value = Decimal("0")
    formatted = f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} руб."


def invoice_deadline_for_payment(payment):
    return payment.due_date - timedelta(weeks=2)
