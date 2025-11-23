from django.db import models


class Client(models.Model):
    """
    Client model - лизингополучатели и страхователи
    """
    client_name = models.CharField('Название компании', max_length=255)
    client_inn = models.CharField('ИНН', max_length=12, blank=True, null=True)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'
        ordering = ['client_name']
        indexes = [
            models.Index(fields=['client_name']),
            models.Index(fields=['client_inn']),
        ]

    def __str__(self):
        return self.client_name
