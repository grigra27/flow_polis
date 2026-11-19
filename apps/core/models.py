"""
Base models and mixins
"""
from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base model with created_at and updated_at fields
    """

    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата обновления", auto_now=True)

    class Meta:
        abstract = True


class ServiceHeartbeat(TimeStampedModel):
    """Отметка последнего успешного запуска фоновой службы (cron/Celery).

    Пишется самими командами (например, daily_digest), читается футером
    и мониторингом: в отличие от кэша, переживает отдельные процессы
    cron-запуска и перезапуски контейнеров.
    """

    key = models.CharField("Ключ службы", max_length=50, unique=True)
    last_success_at = models.DateTimeField("Последний успешный запуск")
    detail = models.CharField("Детали запуска", max_length=200, blank=True)

    class Meta:
        verbose_name = "Отметка фоновой службы"
        verbose_name_plural = "Отметки фоновых служб"

    def __str__(self):
        return f"{self.key} — {self.last_success_at:%d.%m.%Y %H:%M}"
