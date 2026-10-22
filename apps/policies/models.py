from django.db import models
from django.db.models import F, OuterRef, Q, Subquery, Sum
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from decimal import ROUND_CEILING, Decimal
from apps.core.models import TimeStampedModel
from apps.clients.models import Client
from apps.insurers.models import (
    Insurer,
    Branch,
    InsuranceType,
    InfoTag,
    CommissionRate,
    LeasingManager,
    OSAGO_MAX_KV_PERCENT,
)


def in_force_q(as_of, prefix=""):
    """Q-фильтр полисов, действующих («в силе») на дату as_of.

    Полис считается действующим на дату D, если:
    - плановое окно покрывает дату: start_date <= D <= end_date
      (ещё не начавшиеся полисы не считаются действующими);
    - полис не расторгнут досрочно к этой дате: termination_date пуста
      или позже D (до даты расторжения полис ещё в силе);
    - полис не закрыт вручную «без даты»: снятый флаг policy_active без
      termination_date трактуется как закрытый — такие записи нельзя
      восстановить во времени для исторического среза.

    Для D = сегодня определение совпадает с «активен сейчас».

    prefix — путь до Policy от модели запроса: "" для самого Policy,
    "policy__" для PaymentSchedule и т.п.
    """
    return (
        Q(**{f"{prefix}start_date__lte": as_of})
        & Q(**{f"{prefix}end_date__gte": as_of})
        & (
            Q(**{f"{prefix}termination_date__isnull": True})
            | Q(**{f"{prefix}termination_date__gt": as_of})
        )
        & (
            Q(**{f"{prefix}policy_active": True})
            | Q(**{f"{prefix}termination_date__isnull": False})
        )
    )


def osago_q(prefix=""):
    """Q-фильтр полисов ОСАГО (вид страхования с признаком is_osago).

    Портфель делится на «весь» и «без ОСАГО»: каждый отчёт и экран явно
    выбирает одно из двух (см. вопросник ОСАГО, карта влияния). Для
    «без ОСАГО» — ~osago_q(...) или .without_osago().

    prefix — путь до Policy от модели запроса: "" для самого Policy,
    "policy__" для PaymentSchedule и т.п.
    """
    return Q(**{f"{prefix}insurance_type__is_osago": True})


def prolongable_q(prefix=""):
    """Q-фильтр полисов, которые продлевают (вид страхования с признаком
    needs_prolongation). Грузы не продлевают никогда — груз уже доставлен.

    Применяется везде, где речь о пролонгации: раздел и экспорт
    «Пролонгация», метрики продлений в дашборде и аналитике.

    prefix — путь до Policy от модели запроса: "" для самого Policy,
    "policy__" для PaymentSchedule и т.п.
    """
    return Q(**{f"{prefix}insurance_type__needs_prolongation": True})


def add_years(value, years):
    """Дата через `years` лет; 29 февраля → 28 февраля в невисокосный год."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


class PolicyQuerySet(models.QuerySet):
    def in_force(self, as_of=None):
        """Полисы, действующие на дату as_of (по умолчанию — сегодня)."""
        if as_of is None:
            from django.utils import timezone

            as_of = timezone.localdate()
        return self.filter(in_force_q(as_of))

    def osago(self):
        """Только полисы ОСАГО."""
        return self.filter(osago_q())

    def without_osago(self):
        """Портфель без ОСАГО."""
        return self.exclude(osago_q())

    def prolongable(self):
        """Только полисы видов, которые продлевают (без грузов)."""
        return self.filter(prolongable_q())


class PolicyManager(models.Manager.from_queryset(PolicyQuerySet)):
    pass


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
    dfa_deactivation_date = models.DateField(
        "Дата деактивации ДФА",
        blank=True,
        null=True,
        help_text=(
            "Дата, с которой ДФА перестал быть активным. Очередные взносы с "
            "датой платежа после этой даты не попадают на страницу и в экспорт "
            "«Очередные взносы»."
        ),
    )
    policy_uploaded = models.BooleanField("Полис подгружен", default=False)
    broker_participation = models.BooleanField("Участие брокера", default=True)
    renewal_to_old_dfa = models.BooleanField(
        "Перезаключение (к старому ДФА)", default=False
    )
    termination_date = models.DateField(
        "Дата расторжения",
        blank=True,
        null=True,
        help_text="Дата досрочного расторжения полиса",
    )

    objects = PolicyManager()

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

    @property
    def is_osago(self):
        return bool(self.insurance_type_id) and self.insurance_type.is_osago

    def clean(self):
        """Правила ОСАГО: срок не больше года (короткие допустимы), без франшизы.

        Остальные правила ОСАГО (один платёж, нет страховой суммы, КВ ≤ 10%)
        проверяются на уровне платежа — PaymentSchedule.clean().
        """
        from django.core.exceptions import ValidationError

        super().clean()
        if not self.is_osago:
            return

        errors = {}
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                errors[
                    "end_date"
                ] = "Дата окончания не может быть раньше даты начала страхования."
            elif self.end_date > add_years(self.start_date, 1):
                errors["end_date"] = (
                    "Срок полиса ОСАГО не может быть больше года: "
                    f"окончание не позже {add_years(self.start_date, 1):%d.%m.%Y}."
                )
        if self.franchise:
            errors["franchise"] = "У полиса ОСАГО не бывает франшизы."
        if errors:
            raise ValidationError(errors)

    @property
    def premium_total(self):
        """
        Общая сумма страховой премии = сумма всех платежей.
        Считается на лету из графика платежей.

        Для админки/дашборда/дайджеста, которые работают со многими полисами
        сразу, рекомендуется делать annotate(premium_total_db=Sum(...)) на
        queryset, чтобы избежать N+1.
        """
        total = self.payment_schedule.aggregate(total=models.Sum("amount"))["total"]
        return total or Decimal("0")

    @property
    def is_in_force(self):
        """Действует ли полис «в силе» сегодня.

        Учитывает плановое окончание (end_date), досрочное расторжение
        (termination_date) и ручной флаг policy_active. Семантика совпадает
        с фильтром `in_force_q` / `Policy.objects.in_force()`.
        """
        from django.utils import timezone

        today = timezone.localdate()
        if not (self.start_date <= today <= self.end_date):
            return False
        if self.termination_date is not None:
            return self.termination_date > today
        return self.policy_active

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

            # У ОСАГО страховой суммы нет (NULL) — тариф не считается.
            if not first_payment or not first_payment.insurance_sum:
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


class PaymentScheduleQuerySet(models.QuerySet):
    def osago(self):
        """Только платежи полисов ОСАГО."""
        return self.filter(osago_q("policy__"))

    def without_osago(self):
        """Платежи портфеля без ОСАГО."""
        return self.exclude(osago_q("policy__"))


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
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text=(
            "Стоимость застрахованного имущества для данного платежа. "
            "Обязательна для всех видов, кроме ОСАГО (у ОСАГО — пусто)."
        ),
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
    alliance_paid = models.BooleanField("Оплатил Альянс", default=False)
    payment_info = models.TextField("Дополнительная информация", blank=True)

    objects = PaymentScheduleQuerySet.as_manager()

    class Meta:
        verbose_name = "Платеж"
        verbose_name_plural = "График платежей"
        ordering = ["policy", "year_number", "installment_number"]
        unique_together = ["policy", "year_number", "installment_number"]
        indexes = [
            models.Index(fields=["due_date"]),
            models.Index(fields=["paid_date"]),
            models.Index(fields=["paid_date", "due_date"]),
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

        # P2-01 (2026-09-23): year_number/installment_number обязательны на
        # уровне поля (PositiveSmallIntegerField, null=False) — их
        # отсутствием уже занимается clean_fields() внутри full_clean(),
        # которая выполняется ДО этого метода и отдаст понятную
        # ValidationError независимо от того, что делает clean() (Django
        # собирает ошибки со всех трёх этапов full_clean() в один
        # ValidationError). Ранний выход здесь нужен только для того, чтобы
        # не строить Q(year_number__lt=None) — это ValueError, а не
        # ValidationError, и он маскировал полезную ошибку вторичным
        # traceback'ом (см. policy 526, 2026-09-14). Проверено на проде:
        # NULL в этих колонках не бывает (NOT NULL на уровне БД, 0 строк).
        #
        # `pk` в этой проверке намеренно не участвует: у нового
        # несохранённого объекта pk законно равен None, а последовательность
        # дат обязана проверяться и при создании, не только при
        # редактировании — не путать «нет pk» с «не заполнены обязательные
        # поля».
        if (
            not self.policy_id
            or self.year_number is None
            or self.installment_number is None
        ):
            return

        # Правила вида страхования проверяются до любых ранних выходов ниже:
        # formset-путь (H-02) пропускает только проверку порядка дат.
        kind_errors = self.insurance_kind_errors()
        if kind_errors:
            raise ValidationError(kind_errors)

        # H-02 (2026-10-13): в админке полиса порядок дат проверяет
        # PaymentScheduleInlineFormSet.clean() по итоговому набору строк.
        # Здесь сравнение идёт с тем, что УЖЕ лежит в БД, а formset сохраняет
        # строки по одной — промежуточное состояние ломало проверку и
        # ValidationError из save() превращался в HTTP 500.
        if getattr(self, "_date_sequence_checked_by_formset", False):
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

            errors = self.date_sequence_errors(previous_payment)

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

    def insurance_kind_errors(self, policy=None):
        """
        Проверяет платёж по правилам вида страхования полиса.
        `policy` — полис, к которому относится платёж, если он ещё не
        присвоен (inline-formset нового полиса: policy_id пока None).
        ОСАГО: ровно один платёж (год 1, платёж 1), без страховой суммы,
        КВ не больше OSAGO_MAX_KV_PERCENT от премии. Остальные виды: страховая
        сумма обязательна. Возвращает словарь {поле: сообщение}.
        """
        errors = {}
        policy = policy or self.policy
        if not policy.is_osago:
            if self.insurance_sum is None:
                errors["insurance_sum"] = "Укажите страховую сумму."
            return errors

        if (self.year_number, self.installment_number) != (1, 1):
            errors[
                "installment_number"
            ] = "У полиса ОСАГО может быть только один платёж: год 1, платёж 1."
        if self.insurance_sum is not None:
            errors[
                "insurance_sum"
            ] = "У ОСАГО нет страховой суммы — оставьте поле пустым."
        if self.amount and self.kv_rub:
            # Предел округляем вверх до копейки: форма считает КВ как
            # премия × % с обычным округлением, и ровно 10% не должны
            # блокироваться из-за долей копейки.
            kv_limit = (self.amount * OSAGO_MAX_KV_PERCENT / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            if self.kv_rub > kv_limit:
                errors["kv_rub"] = (
                    f"КВ по ОСАГО не может превышать {OSAGO_MAX_KV_PERCENT:g}% "
                    f"от премии ({kv_limit} руб.)."
                )
        return errors

    def date_sequence_errors(self, previous_payment):
        """
        Сравнивает даты платежа с датами предыдущего платежа графика.
        Возвращает словарь {поле: сообщение}; пустой — если порядок верный.
        """
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

        return errors

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


class OsagoPolicy(Policy):
    """Полис ОСАГО — та же таблица полисов, отдельный раздел в админке.

    Прокси нужен только для админки (своя форма: один платёж, без страховой
    суммы и франшизы). Права на раздел — те же, что на обычные полисы
    (решение владельца), см. OsagoPolicyAdmin.has_*_permission.
    """

    class Meta:
        proxy = True
        verbose_name = "Полис ОСАГО"
        verbose_name_plural = "Полисы ОСАГО"


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


def policy_premium_subquery():
    """
    Subquery: сумма amount всех платежей одного полиса.

    Используется в queryset'ах вместо `Sum("premium_total")` —
    поле premium_total больше не хранится в БД (см. миграцию 0017),
    оно вычисляется на лету через @property Policy.premium_total.

    Применение:
        from django.db.models import DecimalField, Subquery, Sum
        from apps.policies.models import policy_premium_subquery

        # Annotate каждого полиса его premium:
        Policy.objects.annotate(
            premium=Subquery(policy_premium_subquery(), output_field=DecimalField())
        )

        # Агрегация по группам полисов:
        Policy.objects.values("branch").annotate(
            total=Sum(Subquery(policy_premium_subquery(), output_field=DecimalField()))
        )

    Subquery вместо прямого `Sum("payment_schedule__amount")` чтобы избежать
    double-counting при JOIN'ах с другими relations (info_tags и т.п.).
    """
    return (
        PaymentSchedule.objects.filter(policy=OuterRef("pk"))
        .values("policy")
        .annotate(total=Sum("amount"))
        .values("total")
    )


def dfa_deactivated_payments_q(prefix=""):
    """Q-фильтр взносов, отсечённых деактивацией ДФА.

    Взнос считается отсечённым, если у полиса снят флаг «ДФА активен»,
    задана «Дата деактивации ДФА» и дата платежа (due_date) позже неё.
    Аналог отсечения по расторжению полиса (termination_date), но для ДФА.

    Используется через `.exclude(dfa_deactivated_payments_q(...))`.

    prefix — путь до PaymentSchedule от модели запроса: "" для самого
    PaymentSchedule, "payment_schedule__" для BillingTask.
    """
    return (
        Q(**{f"{prefix}policy__dfa_active": False})
        & Q(**{f"{prefix}policy__dfa_deactivation_date__isnull": False})
        & Q(**{f"{prefix}due_date__gt": F(f"{prefix}policy__dfa_deactivation_date")})
    )
