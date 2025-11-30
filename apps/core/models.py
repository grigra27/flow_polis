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
