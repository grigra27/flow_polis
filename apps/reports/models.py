from django.db import models
from django.contrib.auth.models import User
from apps.core.models import TimeStampedModel


class CustomExportTemplate(TimeStampedModel):
    """Сохраненные шаблоны кастомных экспортов"""
    
    DATA_SOURCE_CHOICES = [
        ('policies', 'Полисы'),
        ('payments', 'Платежи'),
        ('clients', 'Клиенты'),
        ('insurers', 'Страховщики'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name='Пользователь',
        related_name='export_templates'
    )
    name = models.CharField(
        'Название шаблона',
        max_length=255,
        help_text='Уникальное название для пользователя'
    )
    data_source = models.CharField(
        'Источник данных',
        max_length=50,
        choices=DATA_SOURCE_CHOICES
    )
    config = models.JSONField(
        'Конфигурация',
        help_text='JSON с выбранными полями и фильтрами'
    )
    
    class Meta:
        verbose_name = 'Шаблон экспорта'
        verbose_name_plural = 'Шаблоны экспортов'
        ordering = ['-created_at']
        unique_together = ['user', 'name']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f'{self.name} ({self.get_data_source_display()})'
