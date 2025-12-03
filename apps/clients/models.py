from django.db import models
from django.core.exceptions import ValidationError
import re


def validate_inn(value):
    """
    Валидатор для проверки ИНН.
    ИНН должен содержать только цифры и быть длиной 10 или 12 символов.
    """
    if not value:
        return
    
    # Проверяем, что ИНН содержит только цифры
    if not re.match(r'^\d+$', value):
        raise ValidationError('ИНН должен содержать только цифры.')
    
    # Проверяем длину ИНН
    if len(value) not in [10, 12]:
        raise ValidationError('ИНН должен содержать 10 цифр (для юридических лиц) или 12 цифр (для физических лиц).')


class Client(models.Model):
    """
    Client model - лизингополучатели и страхователи
    """

    client_name = models.CharField("Название компании", max_length=255)
    client_inn = models.CharField(
        "ИНН", 
        max_length=12, 
        blank=True, 
        null=True,
        unique=True,
        validators=[validate_inn],
        help_text="ИНН должен содержать 10 или 12 цифр"
    )
    notes = models.TextField("Примечание", blank=True)

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ["client_name"]
        indexes = [
            models.Index(fields=["client_name"]),
            models.Index(fields=["client_inn"]),
        ]

    def __str__(self):
        return self.client_name
