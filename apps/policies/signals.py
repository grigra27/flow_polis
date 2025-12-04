from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import PaymentSchedule, Policy


@receiver(pre_save, sender=PaymentSchedule)
def calculate_commission(sender, instance, **kwargs):
    """
    Automatically calculate commission in rubles before saving

    Auto-sets commission_rate if not set:
    - Looks up rate based on policy's insurer and insurance_type

    Auto-calculates kv_rub if:
    - It's a new record (no pk yet), OR
    - Commission rate changed and kv_rub wasn't manually edited
    """
    # Auto-set commission_rate if not set
    if not instance.commission_rate and instance.policy_id:
        try:
            from apps.insurers.models import CommissionRate

            # Try to get commission rate from policy's insurer and insurance type
            policy = instance.policy
            rate = CommissionRate.objects.get(
                insurer=policy.insurer, insurance_type=policy.insurance_type
            )
            instance.commission_rate = rate
        except CommissionRate.DoesNotExist:
            # No commission rate found - will be caught by validation if required
            pass
        except Exception:
            # Any other error - don't break the save
            pass

    # If still no commission_rate, can't calculate kv_rub
    if not instance.commission_rate:
        return

    # For new records, always calculate
    if not instance.pk:
        instance.kv_rub = instance.calculate_kv_rub()
        return

    # For existing records, check if commission_rate changed
    try:
        old_instance = PaymentSchedule.objects.get(pk=instance.pk)
        # If commission_rate changed, recalculate (unless user manually changed kv_rub)
        if old_instance.commission_rate != instance.commission_rate:
            # Calculate what the old value should have been
            old_calculated = old_instance.calculate_kv_rub()
            # If current kv_rub matches old calculated value, user didn't edit it manually
            # So we can safely recalculate
            if old_instance.kv_rub == old_calculated:
                instance.kv_rub = instance.calculate_kv_rub()
    except PaymentSchedule.DoesNotExist:
        # Shouldn't happen, but just in case
        instance.kv_rub = instance.calculate_kv_rub()


@receiver([post_save, post_delete], sender=PaymentSchedule)
def update_policy_premium_total(sender, instance, **kwargs):
    """
    Update policy premium_total when payment schedule changes
    """
    policy = instance.policy
    policy.premium_total = policy.calculate_premium_total()
    policy.save(update_fields=["premium_total", "updated_at"])
