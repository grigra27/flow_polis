from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from apps.core.models import TimeStampedModel
from apps.core.file_validators import validate_image_file

# Предельное вознаграждение посредника по ОСАГО, % от премии (решение
# владельца 2026-10-15: превышение запрещено и в ставке, и в платеже).
OSAGO_MAX_KV_PERCENT = Decimal("10")


def get_osago_insurance_type():
    """Вид страхования «ОСАГО» (создаётся миграцией insurers.0014) или None."""
    return InsuranceType.objects.filter(is_osago=True).order_by("pk").first()


class Insurer(models.Model):
    """
    Insurance company - Страховая компания
    """

    insurer_name = models.CharField("Название страховой компании", max_length=255)
    logo = models.ImageField(
        "Логотип",
        upload_to="insurer_logos/",
        blank=True,
        null=True,
        help_text="Рекомендуемый размер: 200x200px. Разрешены: jpg, jpeg, png (макс. 10MB)",
        validators=[validate_image_file],
    )
    contacts = models.URLField(
        "Контакты (ссылка)", blank=True, help_text="Ссылка на yonote"
    )
    email_primary = models.EmailField("Email (основной)", blank=True)
    email_secondary = models.EmailField("Email (дополнительный)", blank=True)
    notes = models.TextField("Примечание", blank=True)

    @property
    def emails(self):
        """Список заполненных e-mail адресов страховщика."""
        return [e for e in (self.email_primary, self.email_secondary) if e]

    class Meta:
        verbose_name = "Страховая компания"
        verbose_name_plural = "Страховые компании"
        ordering = ["insurer_name"]

    def __str__(self):
        return self.insurer_name


class Branch(models.Model):
    """
    Branch - Филиал лизинговой компании
    """

    branch_name = models.CharField("Название филиала", max_length=255)
    logo = models.ImageField(
        "Логотип",
        upload_to="branch_logos/",
        blank=True,
        null=True,
        help_text="Рекомендуемый размер: 200x200px. Разрешены: jpg, jpeg, png (макс. 10MB)",
        validators=[validate_image_file],
    )
    latitude = models.DecimalField(
        "Широта", max_digits=9, decimal_places=6, blank=True, null=True
    )
    longitude = models.DecimalField(
        "Долгота", max_digits=9, decimal_places=6, blank=True, null=True
    )

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"
        ordering = ["branch_name"]

    def __str__(self):
        return self.branch_name


class InsuranceType(models.Model):
    """
    Insurance type - Вид страхования
    """

    name = models.CharField("Вид страхования", max_length=100, unique=True)
    icon = models.ImageField(
        "Иконка",
        upload_to="insurance_type_icons/",
        blank=True,
        null=True,
        help_text="Рекомендуемый размер: 200x200px. Разрешены: jpg, jpeg, png (макс. 10MB)",
        validators=[validate_image_file],
    )
    is_osago = models.BooleanField(
        "ОСАГО",
        default=False,
        help_text=(
            "Полисы этого вида — ОСАГО: один платёж без страховой суммы, срок "
            "не больше года, КВ не больше 10%. В аналитике по страховым "
            "суммам и части отчётов такие полисы не учитываются."
        ),
    )
    needs_prolongation = models.BooleanField(
        "Требует пролонгации",
        default=True,
        help_text=(
            "Снимите, если полисы этого вида не продлеваются (например, грузы: "
            "груз доставлен — продлевать нечего). Такие полисы не попадают в "
            "раздел и экспорт «Пролонгация» и в метрики продлений."
        ),
    )

    class Meta:
        verbose_name = "Вид страхования"
        verbose_name_plural = "Виды страхования"
        ordering = ["name"]

    def __str__(self):
        return self.name


class InfoTag(models.Model):
    """
    Info tags for flexible policy classification
    """

    name = models.CharField("Метка", max_length=100, unique=True)

    class Meta:
        verbose_name = "Инфо-метка"
        verbose_name_plural = "Инфо-метки"
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeasingManager(models.Model):
    """
    Leasing company manager - Менеджер лизинговой компании
    """

    name = models.CharField("Фамилия менеджера", max_length=255, unique=True)
    full_name = models.CharField("Полное ФИО", max_length=255, blank=True)
    phone = models.CharField("Телефон", max_length=50, blank=True)
    email = models.EmailField("Email", blank=True)
    notes = models.TextField("Примечание", blank=True)
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        verbose_name="Филиал",
        related_name="leasing_managers",
    )

    class Meta:
        verbose_name = "Менеджер лизинговой компании"
        verbose_name_plural = "Менеджеры лизинговой компании"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CommissionRateQuerySet(models.QuerySet):
    def for_policy(self, insurer_id, insurance_type_id, start_date):
        """Последняя применимая версия; NULL — исходные условия без нижней границы."""
        if not insurer_id or not insurance_type_id or not start_date:
            return self.none()
        return (
            self.filter(
                insurer_id=insurer_id,
                insurance_type_id=insurance_type_id,
            )
            .filter(
                models.Q(effective_from__isnull=True)
                | models.Q(effective_from__lte=start_date)
            )
            .order_by(models.F("effective_from").desc(nulls_last=True), "-pk")
        )


class CommissionRate(TimeStampedModel):
    """
    Commission rates by insurance type and insurer
    """

    insurer = models.ForeignKey(
        Insurer,
        on_delete=models.CASCADE,
        verbose_name="Страховщик",
        related_name="commission_rates",
    )
    insurance_type = models.ForeignKey(
        InsuranceType,
        on_delete=models.CASCADE,
        verbose_name="Вид страхования",
        related_name="commission_rates",
    )
    kv_percent = models.DecimalField(
        "Ставка комиссии (%)",
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    effective_from = models.DateField(
        "Для полисов с датой начала от",
        null=True,
        blank=True,
        help_text="Включительно. Пустая дата обозначает исходные условия до появления истории ставок.",
    )
    notes = models.TextField("Основание / примечание", blank=True)

    objects = CommissionRateQuerySet.as_manager()

    class Meta:
        verbose_name = "Ставка комиссии"
        verbose_name_plural = "Ставки комиссий"
        constraints = [
            models.UniqueConstraint(
                fields=["insurer", "insurance_type", "effective_from"],
                name="commission_unique_start",
            ),
            models.UniqueConstraint(
                fields=["insurer", "insurance_type"],
                condition=models.Q(effective_from__isnull=True),
                name="commission_unique_baseline",
            ),
        ]
        ordering = ["insurer", "insurance_type", "effective_from", "pk"]

    def __str__(self):
        percent = (
            format(Decimal(self.kv_percent).normalize(), "f")
            if self.kv_percent is not None
            else "—"
        )
        period = (
            f"с {self.effective_from:%d.%m.%Y}"
            if self.effective_from
            else "исходные условия"
        )
        return f"{self.insurer} — {self.insurance_type}: {percent}% ({period})"

    @property
    def is_used(self):
        return bool(self.pk) and (self.payments.exists() or self.policies.exists())

    def clean(self):
        super().clean()
        if self.pk and self.is_used:
            original = type(self).objects.get(pk=self.pk)
            protected = (
                "insurer_id",
                "insurance_type_id",
                "kv_percent",
                "effective_from",
            )
            if any(
                getattr(self, field) != getattr(original, field) for field in protected
            ):
                raise ValidationError(
                    "Ставка используется в полисах или платежах. Добавьте новую версию; "
                    "сохранённые условия изменять нельзя."
                )
        if (
            self.insurance_type_id
            and self.insurance_type.is_osago
            and self.kv_percent is not None
            and self.kv_percent > OSAGO_MAX_KV_PERCENT
        ):
            raise ValidationError(
                {
                    "kv_percent": (
                        f"Ставка КВ по ОСАГО не может превышать "
                        f"{OSAGO_MAX_KV_PERCENT:g}% от премии."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
