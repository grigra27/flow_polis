from django.db import models
from apps.core.models import TimeStampedModel


class Insurer(models.Model):
    """
    Insurance company - Страховая компания
    """
    insurer_name = models.CharField('Название страховой компании', max_length=255)
    logo = models.ImageField(
        'Логотип',
        upload_to='insurer_logos/',
        blank=True,
        null=True,
        help_text='Рекомендуемый размер: 200x200px'
    )
    contacts = models.URLField('Контакты (ссылка)', blank=True, help_text='Ссылка на yonote')
    notes = models.TextField('Примечание', blank=True)

    class Meta:
        verbose_name = 'Страховая компания'
        verbose_name_plural = 'Страховые компании'
        ordering = ['insurer_name']

    def __str__(self):
        return self.insurer_name


class Branch(models.Model):
    """
    Branch - Филиал лизинговой компании
    """
    branch_name = models.CharField('Название филиала', max_length=255)
    logo = models.ImageField(
        'Логотип',
        upload_to='branch_logos/',
        blank=True,
        null=True,
        help_text='Рекомендуемый размер: 200x200px'
    )

    class Meta:
        verbose_name = 'Филиал'
        verbose_name_plural = 'Филиалы'
        ordering = ['branch_name']

    def __str__(self):
        return self.branch_name


class InsuranceType(models.Model):
    """
    Insurance type - Вид страхования
    """
    name = models.CharField('Вид страхования', max_length=100, unique=True)
    icon = models.ImageField(
        'Иконка',
        upload_to='insurance_type_icons/',
        blank=True,
        null=True,
        help_text='Рекомендуемый размер: 200x200px'
    )

    class Meta:
        verbose_name = 'Вид страхования'
        verbose_name_plural = 'Виды страхования'
        ordering = ['name']

    def __str__(self):
        return self.name


class InfoTag(models.Model):
    """
    Info tags for flexible policy classification
    """
    name = models.CharField('Метка', max_length=100, unique=True)

    class Meta:
        verbose_name = 'Инфо-метка'
        verbose_name_plural = 'Инфо-метки'
        ordering = ['name']

    def __str__(self):
        return self.name


class LeasingManager(models.Model):
    """
    Leasing company manager - Менеджер лизинговой компании
    """
    name = models.CharField('Фамилия менеджера', max_length=255, unique=True)
    full_name = models.CharField('Полное ФИО', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=50, blank=True)
    email = models.EmailField('Email', blank=True)
    notes = models.TextField('Примечание', blank=True)

    class Meta:
        verbose_name = 'Менеджер лизинговой компании'
        verbose_name_plural = 'Менеджеры лизинговой компании'
        ordering = ['name']

    def __str__(self):
        return self.name


class CommissionRate(TimeStampedModel):
    """
    Commission rates by insurance type and insurer
    """
    insurer = models.ForeignKey(
        Insurer,
        on_delete=models.CASCADE,
        verbose_name='Страховщик',
        related_name='commission_rates'
    )
    insurance_type = models.ForeignKey(
        InsuranceType,
        on_delete=models.CASCADE,
        verbose_name='Вид страхования',
        related_name='commission_rates'
    )
    kv_percent = models.DecimalField(
        'Ставка комиссии (%)',
        max_digits=5,
        decimal_places=2
    )

    class Meta:
        verbose_name = 'Ставка комиссии'
        verbose_name_plural = 'Ставки комиссий'
        unique_together = ['insurer', 'insurance_type']
        ordering = ['insurer', 'insurance_type']

    def __str__(self):
        return f'{self.insurer} - {self.insurance_type}: {int(round(float(self.kv_percent)))}%'
