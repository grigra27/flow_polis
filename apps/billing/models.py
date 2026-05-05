import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

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

    def _get_installment_metadata(self):
        payment = self.payment_schedule
        payments_in_year = self.policy.payment_schedule.filter(
            year_number=payment.year_number
        ).count()
        if payment.installment_number != 1 or payments_in_year > 1:
            installment_status = "рассрочка"
        else:
            installment_status = "годовой"
        payments_total_in_year = (
            payments_in_year if payments_in_year else payment.installment_number
        )
        payment_position = f"{payment.installment_number} из {payments_total_in_year}"
        return installment_status, payments_total_in_year, payment_position

    @staticmethod
    def _get_request_subject_line(installment_status):
        if installment_status == "годовой":
            return "Просим выставить счет на годовой взнос по договору страхования:"
        return "Просим выставить счет на очередной взнос по договору страхования:"

    @staticmethod
    def _get_outgoing_lead_line(installment_status):
        if installment_status == "годовой":
            return "Высылаем счет на годовой взнос по договору страхования."
        return "Высылаем счет на очередной взнос по договору страхования."

    def build_letter_subject(self):
        policy = self.policy
        installment_status, _, _ = self._get_installment_metadata()
        if installment_status == "годовой":
            subject_prefix = "Счёт на годовой взнос"
        else:
            subject_prefix = "Счёт на очередной взнос"
        dfa_number = policy.dfa_number or "Без ДФА"
        policy_number = policy.policy_number or "Без номера полиса"
        return f"{subject_prefix} --- {dfa_number} --- {policy_number}"

    def build_letter_text(self):
        policy = self.policy
        installment_status, _, _ = self._get_installment_metadata()

        critical_block = [
            f"Номер полиса: {policy.policy_number}",
            f"Дата платежа по договору: {self.due_date.strftime('%d.%m.%Y')}",
            f"Сумма очередного взноса: {format_money(self.amount)}",
        ]

        context_block = [
            f"Номер ДФА: {policy.dfa_number or ''}",
            f"Страховщик: {policy.insurer.insurer_name}",
        ]
        if policy.policyholder:
            context_block.append(f"Страхователь: {policy.policyholder.client_name}")
        context_block.extend(
            [
                f"Лизингополучатель: {policy.client.client_name}",
                f"Объект страхования: {policy.property_description}",
            ]
        )

        blocks = [
            ["Добрый день."],
            [self._get_request_subject_line(installment_status)],
            critical_block,
            context_block,
            ["Просим направить счет для дальнейшей передачи в оплату."],
            ["Спасибо."],
        ]
        return "\n\n".join("\n".join(block) for block in blocks)

    def build_letter_html(self):
        return self._wrap_letter_html(self.build_letter_text())

    def build_alliance_letter_subject(self):
        dfa_number = self.policy.dfa_number or "Без ДФА"
        insurer_name = (
            self.policy.insurer.insurer_name or ""
        ).strip() or "Без страховщика"
        return f"СТРАХОВАНИЕ --- счет --- {dfa_number} --- {insurer_name}"

    def build_alliance_letter_text(self):
        policy = self.policy
        payment = self.payment_schedule
        (
            installment_status,
            _payments_total_in_year,
            payment_position,
        ) = self._get_installment_metadata()

        # В письме в Альянс указываем дату платежа на день раньше
        # фактической из базы — это технологический сдвиг лизинговой
        # компании (нужно успеть провести оплату до дедлайна СК).
        alliance_due_date = self.due_date - timedelta(days=1)
        alliance_due_str = alliance_due_date.strftime("%d.%m.%Y")

        def _fmt_date(value):
            return value.strftime("%d.%m.%Y") if value else "—"

        contract_block = [
            "ДОГОВОР СТРАХОВАНИЯ",
            f"Номер ДФА: {policy.dfa_number or '—'}",
            f"Номер полиса: {policy.policy_number}",
            "Период договора страхования: "
            f"{_fmt_date(policy.start_date)} — {_fmt_date(policy.end_date)}",
        ]
        if policy.policyholder:
            contract_block.append(f"Страхователь: {policy.policyholder.client_name}")
        contract_block.extend(
            [
                f"Объект страхования: {policy.property_description or '—'}",
            ]
        )

        if installment_status == "годовой":
            payment_type_line = "Тип взноса: годовой"
        else:
            payment_type_line = f"Тип взноса: рассрочка, платёж {payment_position}"

        payment_block = [
            "ПЛАТЁЖ",
            f"Оплатить до: {alliance_due_str}",
            f"Сумма к оплате: {format_money(self.amount)}",
            f"Страховая сумма: {format_money(payment.insurance_sum)}",
            f"Год страхования: {payment.year_number} год страхования",
            payment_type_line,
        ]

        blocks = [
            ["Добрый день."],
            [self._get_outgoing_lead_line(installment_status)],
            contract_block,
            payment_block,
            [f"Просим оплатить счет до {alliance_due_str} включительно."],
            ["Спасибо."],
        ]
        return "\n\n".join("\n".join(block) for block in blocks)

    def build_alliance_letter_html(self):
        return self._wrap_letter_html(
            self.build_alliance_letter_text(),
            section_headers={"ДОГОВОР СТРАХОВАНИЯ", "ПЛАТЁЖ"},
        )

    @staticmethod
    def _wrap_letter_html(text, section_headers=None):
        # Превращает plain-текст письма в HTML, оборачивая значения после
        # двоеточий и явные заголовки секций в <strong>. Используется и для
        # СК, и для Альянса — структура та же, отличается только набор
        # известных заголовков. Все пользовательские данные экранируются
        # через escape/format_html — гарантия от XSS.
        section_headers = section_headers or set()
        parts = []
        for line in text.split("\n"):
            if not line:
                parts.append("")
                continue
            if line in section_headers:
                parts.append(format_html("<strong>{}</strong>", line))
                continue
            label, sep, value = line.partition(":")
            if sep and value.strip():
                parts.append(
                    format_html("{}: <strong>{}</strong>", label, value.strip())
                )
                continue
            parts.append(escape(line))
        return mark_safe("<br>".join(parts))


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
