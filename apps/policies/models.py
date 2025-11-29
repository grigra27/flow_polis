from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from apps.core.models import TimeStampedModel
from apps.clients.models import Client
from apps.insurers.models import Insurer, Branch, InsuranceType, InfoTag, CommissionRate, LeasingManager


class Policy(TimeStampedModel):
    """
    Insurance Policy - Страховой полис
    """
    policy_number = models.CharField('Номер полиса', max_length=100)
    dfa_number = models.CharField('Номер ДФА', max_length=100, blank=True)
    
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        verbose_name='Лизингополучатель',
        related_name='policies'
    )
    policyholder = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        verbose_name='Страхователь',
        related_name='policyholder_policies',
        blank=True,
        null=True
    )
    insurer = models.ForeignKey(
        Insurer,
        on_delete=models.PROTECT,
        verbose_name='Страховщик',
        related_name='policies'
    )
    
    property_description = models.TextField('Описание застрахованного имущества')
    property_year = models.IntegerField(
        'Год выпуска имущества',
        blank=True,
        null=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
        help_text='Год выпуска застрахованного имущества (1900-2100)'
    )
    start_date = models.DateField('Дата начала страхования')
    end_date = models.DateField('Дата окончания страхования')
    
    premium_total = models.DecimalField(
        'Общая сумма страховой премии',
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text='Рассчитывается автоматически из графика платежей'
    )
    
    insurance_type = models.ForeignKey(
        InsuranceType,
        on_delete=models.PROTECT,
        verbose_name='Вид страхования',
        related_name='policies'
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        verbose_name='Филиал',
        related_name='policies'
    )
    
    leasing_manager = models.ForeignKey(
        LeasingManager,
        on_delete=models.PROTECT,
        verbose_name='Менеджер лизинговой компании',
        related_name='policies',
        blank=True,
        null=True
    )
    franchise = models.DecimalField(
        'Франшиза',
        max_digits=15,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal('0'))]
    )
    
    info3 = models.TextField('Инфо 3 (видно в журнале)', blank=True)
    info4 = models.TextField('Инфо 4 (не видно в журнале)', blank=True)
    
    policy_active = models.BooleanField('Полис активен', default=True)
    dfa_active = models.BooleanField('ДФА активен', default=True)
    policy_uploaded = models.BooleanField('Полис подгружен', default=False)
    broker_participation = models.BooleanField('Участие брокера', default=True)
    termination_date = models.DateField(
        'Дата расторжения',
        blank=True,
        null=True,
        help_text='Дата досрочного расторжения полиса'
    )

    class Meta:
        verbose_name = 'Полис'
        verbose_name_plural = 'Полисы'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['policy_number']),
            models.Index(fields=['dfa_number']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['policy_active']),
            models.Index(fields=['policy_uploaded']),
        ]

    def __str__(self):
        return f'{self.policy_number} - {self.client}'

    def calculate_premium_total(self):
        """Calculate total premium from payment schedule"""
        total = self.payment_schedule.aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')
        return total


class PaymentSchedule(TimeStampedModel):
    """
    Payment Schedule - График платежей
    """
    policy = models.ForeignKey(
        Policy,
        on_delete=models.CASCADE,
        verbose_name='Полис',
        related_name='payment_schedule'
    )
    
    year_number = models.PositiveSmallIntegerField('Порядковый номер года')
    installment_number = models.PositiveSmallIntegerField('Порядковый номер платежа')
    
    due_date = models.DateField('Дата платежа (по договору)')
    amount = models.DecimalField(
        'Сумма платежа',
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    insurance_sum = models.DecimalField(
        'Страховая сумма',
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Стоимость застрахованного имущества для данного платежа'
    )
    
    commission_rate = models.ForeignKey(
        CommissionRate,
        on_delete=models.PROTECT,
        verbose_name='Ставка комиссии',
        related_name='payments',
        blank=True,
        null=True
    )
    kv_rub = models.DecimalField(
        'Комиссия (руб)',
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text='Рассчитывается автоматически, но можно изменить вручную'
    )
    
    paid_date = models.DateField('Фактическая дата оплаты', blank=True, null=True)
    insurer_date = models.DateField('Дата согласования СК', blank=True, null=True)
    payment_info = models.TextField('Дополнительная информация', blank=True)

    class Meta:
        verbose_name = 'Платеж'
        verbose_name_plural = 'График платежей'
        ordering = ['policy', 'year_number', 'installment_number']
        indexes = [
            models.Index(fields=['due_date']),
            models.Index(fields=['paid_date']),
        ]

    def __str__(self):
        return f'{self.policy.policy_number} - Год {self.year_number}, Платеж {self.installment_number}'

    def calculate_kv_rub(self):
        """Calculate commission in rubles"""
        if self.commission_rate:
            return self.amount * (self.commission_rate.kv_percent / Decimal('100'))
        return Decimal('0')

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
            return (self.kv_rub / self.amount) * Decimal('100')
        return Decimal('0')


class PolicyInfo(TimeStampedModel):
    """
    Policy Info Tags - Связка полис ↔ метки
    """
    INFO_FIELD_CHOICES = [
        (1, 'Инфо 1'),
        (2, 'Инфо 2'),
    ]
    
    policy = models.ForeignKey(
        Policy,
        on_delete=models.CASCADE,
        verbose_name='Полис',
        related_name='info_tags'
    )
    tag = models.ForeignKey(
        InfoTag,
        on_delete=models.CASCADE,
        verbose_name='Метка',
        related_name='policy_infos'
    )
    info_field = models.PositiveSmallIntegerField(
        'Поле',
        choices=INFO_FIELD_CHOICES
    )

    class Meta:
        verbose_name = 'Инфо-метка полиса'
        verbose_name_plural = 'Инфо-метки полисов'
        unique_together = ['policy', 'tag', 'info_field']

    def __str__(self):
        return f'{self.policy.policy_number} - {self.tag.name} (Инфо {self.info_field})'
