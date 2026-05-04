import logging

from celery import shared_task

from .services import sync_period, visible_period_months

logger = logging.getLogger(__name__)


@shared_task
def sync_billing_periods():
    """
    Создаёт/обновляет задачи очередных взносов для всех видимых месяцев.

    Заводится в django_celery_beat (например, ежедневно в 00:30) — тогда
    тяжёлая часть синхронизации не выполняется на каждый GET страницы.
    """
    months = visible_period_months()
    synced = 0
    for month in months:
        try:
            sync_period(month.year, month.month)
            synced += 1
        except Exception:
            logger.exception(
                "Failed to sync billing period %04d-%02d", month.year, month.month
            )
    return f"synced {synced}/{len(months)} periods"
