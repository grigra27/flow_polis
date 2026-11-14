import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import PaymentSchedule

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=PaymentSchedule)
def calculate_commission(sender, instance, raw=False, **kwargs):
    """Новый взнос наследует условия полиса; существующий не пересчитывается."""
    if raw or not instance._state.adding or not instance.policy_id:
        return
    if not instance.commission_rate_id:
        instance.commission_rate = instance.policy.default_commission_rate
    if not instance.commission_rate_id:
        logger.info(
            "No commission rate configured for policy %s (insurer=%s, insurance_type=%s) — kv_rub left unchanged",
            instance.policy_id,
            instance.policy.insurer_id,
            instance.policy.insurance_type_id,
        )
        return
    if not getattr(instance, "_explicit_commission", False):
        instance.kv_rub = instance.calculate_kv_rub()
