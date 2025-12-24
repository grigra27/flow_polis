from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from decimal import Decimal
from apps.core.models import TimeStampedModel
from apps.clients.models import Client
from apps.insurers.models import (
    Insurer,
    Branch,
    InsuranceType,
    InfoTag,
    CommissionRate,
    LeasingManager,
)


class Policy(TimeStampedModel):
    """
    Insurance Policy - Страховой полис
    """

    policy_number = models.CharField("Номер полиса", max_length=100)
    dfa_number = models.CharField("Номер ДФА", max_length=100, blank=True)

    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        verbose_name="Лизингополучатель",
        related_name="policies",
    )
    policyholder = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        verbose_name="Страхователь",
        related_name="policyholder_policies",
        blank=True,
        null=True,
    )
    insurer = models.ForeignKey(
        Insurer,
        on_delete=models.PROTECT,
        verbose_name="Страховщик",
        related_name="policies",
    )

    property_description = models.TextField("Описание застрахованного имущества")
    property_year = models.IntegerField(
        "Год выпуска имущества",
        blank=True,
        null=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
        help_text="Год выпуска застрахованного имущества (1900-2100)",
    )
    vin_number = models.CharField(
        "Идентификатор (обычно VIN)",
        max_length=17,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Z0-9]{3,17}$",
                message="Идентификатор должен состоять из 3-17 символов, включающих латинские буквы и цифры",
                code="invalid_identifier",
            )
        ],
        help_text="Идентификатор транспортного средства (3-17 символов, латинские буквы и цифры)",
    )
    start_date = models.DateField("Дата начала страхования")
    end_date = models.DateField("Дата окончания страхования")

    premium_total = models.DecimalField(
        "Общая сумма страховой премии",
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Рассчитывается автоматически из графика платежей",
    )

    insurance_type = models.ForeignKey(
        InsuranceType,
        on_delete=models.PROTECT,
        verbose_name="Вид страхования",
        related_name="policies",
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, verbose_name="Филиал", related_name="policies"
    )

    leasing_manager = models.ForeignKey(
        LeasingManager,
        on_delete=models.PROTECT,
        verbose_name="Менеджер лизинговой компании",
        related_name="policies",
        blank=True,
        null=True,
    )
    franchise = models.DecimalField(
        "Франшиза",
        max_digits=15,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )

    info3 = models.TextField("Инфо 3 (видно в журнале)", blank=True)
    info4 = models.TextField("Инфо 4 (не видно в журнале)", blank=True)

    policy_active = models.BooleanField("Полис активен", default=True)
    dfa_active = models.BooleanField("ДФА активен", default=True)
    policy_uploaded = models.BooleanField("Полис подгружен", default=False)
    broker_participation = models.BooleanField("Участие брокера", default=True)
    termination_date = models.DateField(
        "Дата расторжения",
        blank=True,
        null=True,
        help_text="Дата досрочного расторжения полиса",
    )

    class Meta:
        verbose_name = "Полис"
        verbose_name_plural = "Полисы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["policy_number"]),
            models.Index(fields=["dfa_number"]),
            models.Index(fields=["start_date", "end_date"]),
            models.Index(fields=["policy_active"]),
            models.Index(fields=["policy_uploaded"]),
        ]

    def __str__(self):
        return f"{self.policy_number} - {self.client}"

    def calculate_premium_total(self):
        """Calculate total premium from payment schedule"""
        total = self.payment_schedule.aggregate(total=models.Sum("amount"))[
            "total"
        ] or Decimal("0")
        return total

    def get_rates_by_year(self):
        """
        Calculate insurance rates by year.

        Returns a list of dictionaries with year_number, total_premium,
        insurance_sum (from first payment of the year), rate (as percentage),
        and is_current flag.

        Rate is calculated as: (sum of all premiums for the year / insurance_sum) * 100

        Current year is determined by:
        - First payment of this year has occurred (due_date <= today)
        - First payment of next year has not occurred yet (due_date > today or doesn't exist)

        IMPORTANT: Only years where the first payment (installment_number=1) exists
        are included in the calculation. This prevents incorrect calculations for years
        where only later installments were entered into the database.
        """
        from django.db.models import Sum, Min
        from datetime import date

        today = date.today()

        # Query 1: Group payments by year_number
        years_data = (
            self.payment_schedule.values("year_number")
            .annotate(
                total_premium=Sum("amount"), min_installment=Min("installment_number")
            )
            .order_by("year_number")
        )

        # Query 2: Get ALL first payments at once (optimized)
        first_payments = {
            p.year_number: p
            for p in self.payment_schedule.filter(installment_number=1).select_related()
        }

        rates_by_year = []
        for year_data in years_data:
            year_number = year_data["year_number"]
            min_installment = year_data["min_installment"]

            # Skip this year if the first payment (installment_number=1) doesn't exist
            # This prevents incorrect calculations when only later installments are in the database
            if min_installment != 1:
                continue

            total_premium = year_data["total_premium"] or Decimal("0")

            # Get first payment from dictionary (no additional DB query)
            first_payment = first_payments.get(year_number)

            if not first_payment or first_payment.insurance_sum <= 0:
                continue

            # Determine if this is the current year
            current_year_started = first_payment.due_date <= today

            # Check if next year has started
            next_year_payment = first_payments.get(year_number + 1)
            next_year_not_started = (
                next_year_payment is None or next_year_payment.due_date > today
            )

            is_current = current_year_started and next_year_not_started

            # Calculate rate
            insurance_sum = first_payment.insurance_sum
            rate = (total_premium / insurance_sum) * Decimal("100")

            rates_by_year.append(
                {
                    "year_number": year_number,
                    "total_premium": total_premium,
                    "insurance_sum": insurance_sum,
                    "rate": rate,
                    "is_current": is_current,
                }
            )

        return rates_by_year


class PaymentSchedule(TimeStampedModel):
    """
    Payment Schedule - График платежей
    """

    policy = models.ForeignKey(
        Policy,
        on_delete=models.CASCADE,
        verbose_name="Полис",
        related_name="payment_schedule",
    )

    year_number = models.PositiveSmallIntegerField("Порядковый номер года")
    installment_number = models.PositiveSmallIntegerField("Порядковый номер платежа")

    due_date = models.DateField("Дата платежа (по договору)")
    insurance_sum = models.DecimalField(
        "Страховая сумма",
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Стоимость застрахованного имущества для данного платежа",
    )
    amount = models.DecimalField(
        "Страховая премия",
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    commission_rate = models.ForeignKey(
        CommissionRate,
        on_delete=models.PROTECT,
        verbose_name="Ставка комиссии",
        related_name="payments",
        blank=True,
        null=True,
    )
    kv_rub = models.DecimalField(
        "Комиссия (руб)",
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Рассчитывается автоматически, но можно изменить вручную",
    )

    paid_date = models.DateField("Фактическая дата оплаты", blank=True, null=True)
    insurer_date = models.DateField(
        "Дата согласования акта с СК", blank=True, null=True
    )
    payment_info = models.TextField("Дополнительная информация", blank=True)

    class Meta:
        verbose_name = "Платеж"
        verbose_name_plural = "График платежей"
        ordering = ["policy", "year_number", "installment_number"]
        unique_together = ["policy", "year_number", "installment_number"]
        indexes = [
            models.Index(fields=["due_date"]),
            models.Index(fields=["paid_date"]),
        ]

    def __str__(self):
        return f"{self.policy.policy_number} - Год {self.year_number}, Платеж {self.installment_number}"

    def clean(self):
        """
        Валидация дат платежа.
        Проверяет, что даты текущего платежа не раньше дат предыдущих платежей.
        """
        from django.core.exceptions import ValidationError
        import logging

        logger = logging.getLogger(__name__)

        if not self.policy_id:
            return

        try:
            # Находим предыдущий платеж с защитой от race conditions
            previous_payment = (
                PaymentSchedule.objects.filter(policy=self.policy)
                .exclude(pk=self.pk)  # Исключаем текущий платеж при редактировании
                .filter(
                    models.Q(year_number__lt=self.year_number)
                    | models.Q(
                        year_number=self.year_number,
                        installment_number__lt=self.installment_number,
                    )
                )
                .order_by("-year_number", "-installment_number")
                .first()
            )

            if not previous_payment:
                return  # Это первый платеж, валидация не нужна

            errors = {}

            # Проверяем дату по договору
            if self.due_date and previous_payment.due_date:
                if self.due_date <= previous_payment.due_date:
                    errors["due_date"] = (
                        f"Дата платежа по договору ({self.due_date}) не может быть раньше или равна "
                        f"дате предыдущего платежа ({previous_payment.due_date}). "
                        f"Предыдущий платеж: Год {previous_payment.year_number}, "
                        f"Платеж {previous_payment.installment_number}."
                    )

            # Проверяем фактическую дату оплаты (только если обе даты заполнены)
            if self.paid_date and previous_payment.paid_date:
                if self.paid_date <= previous_payment.paid_date:
                    errors["paid_date"] = (
                        f"Фактическая дата оплаты ({self.paid_date}) не может быть раньше или равна "
                        f"дате оплаты предыдущего платежа ({previous_payment.paid_date}). "
                        f"Предыдущий платеж: Год {previous_payment.year_number}, "
                        f"Платеж {previous_payment.installment_number}."
                    )

            # Проверяем дату согласования СК (только если обе даты заполнены)
            if self.insurer_date and previous_payment.insurer_date:
                if self.insurer_date <= previous_payment.insurer_date:
                    errors["insurer_date"] = (
                        f"Дата согласования акта с СК ({self.insurer_date}) не может быть раньше или равна "
                        f"дате согласования предыдущего платежа ({previous_payment.insurer_date}). "
                        f"Предыдущий платеж: Год {previous_payment.year_number}, "
                        f"Платеж {previous_payment.installment_number}."
                    )

            if errors:
                logger.warning(
                    f"Payment validation errors for policy {self.policy_id}, "
                    f"year {self.year_number}, installment {self.installment_number}: {errors}"
                )
                raise ValidationError(errors)

        except ValidationError:
            # Re-raise validation errors as they are expected
            raise
        except Exception as e:
            # Log unexpected errors but don't break the save
            logger.error(
                f"Unexpected error in PaymentSchedule.clean() for policy {self.policy_id}, "
                f"year {getattr(self, 'year_number', 'unknown')}, "
                f"installment {getattr(self, 'installment_number', 'unknown')}: {e}",
                exc_info=True,
            )
            # Don't raise - allow save to continue with a warning
            logger.warning(
                f"Skipping date validation for payment due to error. "
                f"Manual review recommended for policy {self.policy_id}"
            )

    def save(self, *args, **kwargs):
        """Переопределяем save для вызова валидации"""
        self.full_clean()
        super().save(*args, **kwargs)

    def calculate_kv_rub(self):
        """Calculate commission in rubles"""
        if self.commission_rate:
            return self.amount * (self.commission_rate.kv_percent / Decimal("100"))
        return Decimal("0")

    @property
    def is_paid(self):
        return self.paid_date is not None

    @property
    def is_approved(self):
        """Платеж согласован со страховой компанией"""
        return self.insurer_date is not None

    @property
    def is_overdue(self):
        from django.utils import timezone

        if self.is_paid:
            return False
        # Если полис неактивен, платеж не является неоплаченным, а отменен
        if not self.policy.policy_active:
            return False
        return self.due_date < timezone.now().date()

    @property
    def is_cancelled(self):
        """Платеж отменен из-за расторжения полиса"""
        # Платеж отменен, если он не оплачен и полис неактивен
        # и дата платежа после даты расторжения (если она указана)
        if self.is_paid or self.policy.policy_active:
            return False

        # Если есть дата расторжения, проверяем что платеж был после нее
        if self.policy.termination_date:
            return self.due_date > self.policy.termination_date

        # Если даты расторжения нет, но полис неактивен - считаем отмененным
        return True

    @property
    def kv_percent_actual(self):
        """Фактический процент КВ, рассчитанный из КВ руб и премии"""
        if self.amount and self.amount > 0:
            return (self.kv_rub / self.amount) * Decimal("100")
        return Decimal("0")


class PolicyInfo(TimeStampedModel):
    """
    Policy Info Tags - Связка полис ↔ метки
    """

    INFO_FIELD_CHOICES = [
        (1, "Инфо 1"),
        (2, "Инфо 2"),
    ]

    policy = models.ForeignKey(
        Policy, on_delete=models.CASCADE, verbose_name="Полис", related_name="info_tags"
    )
    tag = models.ForeignKey(
        InfoTag,
        on_delete=models.CASCADE,
        verbose_name="Метка",
        related_name="policy_infos",
    )
    info_field = models.PositiveSmallIntegerField("Поле", choices=INFO_FIELD_CHOICES)

    class Meta:
        verbose_name = "Инфо-метка полиса"
        verbose_name_plural = "Инфо-метки полисов"
        unique_together = ["policy", "tag", "info_field"]

    def __str__(self):
        return f"{self.policy.policy_number} - {self.tag.name} (Инфо {self.info_field})"
