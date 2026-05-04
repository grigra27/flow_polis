import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.policies.models import PaymentSchedule, Policy

logger = logging.getLogger(__name__)


@receiver(post_save, sender=PaymentSchedule)
def actualize_billing_task_for_payment(sender, instance, **kwargs):
    """
    Поддерживает связанную задачу очередного взноса в актуальном состоянии:
    при оплате или деактивации полиса задача удаляется,
    при переносе due_date пересчитывается deadline и периодная привязка.
    """
    from .models import BillingPeriod, BillingTask, BillingTaskEvent
    from .services import invoice_deadline_for_due_date

    try:
        task = BillingTask.objects.select_related("period").get(
            payment_schedule=instance
        )
    except BillingTask.DoesNotExist:
        return

    if instance.paid_date is not None or not instance.policy.policy_active:
        task.delete()
        return

    new_deadline = invoice_deadline_for_due_date(instance.due_date)
    new_year = instance.due_date.year
    new_month = instance.due_date.month

    update_fields = []
    new_period_label = None

    if task.period.year != new_year or task.period.month != new_month:
        new_period, _ = BillingPeriod.objects.get_or_create(
            year=new_year, month=new_month
        )
        if new_period.id != task.period_id:
            task.period = new_period
            update_fields.append("period")
            new_period_label = new_period.code

    if task.invoice_request_deadline != new_deadline:
        task.invoice_request_deadline = new_deadline
        update_fields.append("invoice_request_deadline")

    if not update_fields:
        return

    with transaction.atomic():
        task.save(update_fields=[*update_fields, "updated_at"])
        comment_parts = []
        if new_period_label:
            comment_parts.append(f"период → {new_period_label}")
        if "invoice_request_deadline" in update_fields:
            comment_parts.append(f"дедлайн → {new_deadline.isoformat()}")
        BillingTaskEvent.objects.create(
            task=task,
            event_type=BillingTaskEvent.EVENT_SYNCED,
            comment="Платёж изменён: " + ", ".join(comment_parts),
        )


@receiver(post_save, sender=Policy)
def cleanup_billing_tasks_for_inactive_policy(sender, instance, **kwargs):
    """При деактивации полиса снимает все связанные задачи очередных взносов."""
    from .models import BillingTask

    if instance.policy_active:
        return

    BillingTask.objects.filter(payment_schedule__policy=instance).delete()
