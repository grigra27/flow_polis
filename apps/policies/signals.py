import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import PaymentSchedule, Policy

logger = logging.getLogger(__name__)


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
    try:
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
                logger.info(
                    f"Auto-set commission rate {rate.id} for payment "
                    f"policy={policy.id}, insurer={policy.insurer.id}, "
                    f"insurance_type={policy.insurance_type.id}"
                )
            except CommissionRate.DoesNotExist:
                # No commission rate found - log warning but don't break save
                logger.warning(
                    f"Commission rate not found for policy {instance.policy_id}: "
                    f"insurer={instance.policy.insurer.id}, "
                    f"insurance_type={instance.policy.insurance_type.id}"
                )
                return  # Exit early if no commission rate
            except Exception as e:
                # Any other error - log but don't break the save
                logger.error(
                    f"Unexpected error getting commission rate for policy {instance.policy_id}: {e}",
                    exc_info=True,
                )
                return  # Exit early on error

        # If still no commission_rate, can't calculate kv_rub
        if not instance.commission_rate:
            return

        # For new records, always calculate
        if not instance.pk:
            try:
                instance.kv_rub = instance.calculate_kv_rub()
                logger.debug(f"Calculated kv_rub for new payment: {instance.kv_rub}")
            except Exception as e:
                logger.error(
                    f"Error calculating kv_rub for new payment: {e}", exc_info=True
                )
                # Don't break save, just leave kv_rub as is
            return

        # For existing records, check if commission_rate changed
        try:
            old_instance = PaymentSchedule.objects.get(pk=instance.pk)
            # If commission_rate changed, recalculate (unless user manually changed kv_rub)
            if old_instance.commission_rate != instance.commission_rate:
                try:
                    # Calculate what the old value should have been
                    old_calculated = old_instance.calculate_kv_rub()
                    # If current kv_rub matches old calculated value, user didn't edit it manually
                    # So we can safely recalculate
                    if old_instance.kv_rub == old_calculated:
                        instance.kv_rub = instance.calculate_kv_rub()
                        logger.debug(
                            f"Recalculated kv_rub for payment {instance.pk}: {instance.kv_rub}"
                        )
                except Exception as e:
                    logger.error(
                        f"Error recalculating kv_rub for payment {instance.pk}: {e}",
                        exc_info=True,
                    )
                    # Don't break save, just leave kv_rub as is
        except PaymentSchedule.DoesNotExist:
            # Shouldn't happen, but just in case - treat as new record
            logger.warning(
                f"PaymentSchedule {instance.pk} not found during update, treating as new"
            )
            try:
                instance.kv_rub = instance.calculate_kv_rub()
            except Exception as e:
                logger.error(
                    f"Error calculating kv_rub for 'new' payment {instance.pk}: {e}",
                    exc_info=True,
                )
        except Exception as e:
            logger.error(
                f"Unexpected error in commission calculation for payment {instance.pk}: {e}",
                exc_info=True,
            )
            # Don't break save

    except Exception as e:
        # Catch-all for any unexpected errors in the entire signal
        logger.error(
            f"Critical error in calculate_commission signal for payment "
            f"(policy_id={getattr(instance, 'policy_id', 'unknown')}): {e}",
            exc_info=True,
        )
        # Don't re-raise - let the save continue


@receiver([post_save, post_delete], sender=PaymentSchedule)
def update_policy_premium_total(sender, instance, **kwargs):
    """
    Update policy premium_total when payment schedule changes
    """
    try:
        policy = instance.policy

        # Calculate new total
        old_total = policy.premium_total
        new_total = policy.calculate_premium_total()

        # Only update if total actually changed to avoid unnecessary saves
        if old_total != new_total:
            policy.premium_total = new_total
            # Use update_fields to avoid triggering other signals/validations
            policy.save(update_fields=["premium_total", "updated_at"])

            logger.debug(
                f"Updated policy {policy.id} premium_total: {old_total} -> {new_total}"
            )
        else:
            logger.debug(f"Policy {policy.id} premium_total unchanged: {old_total}")

    except Exception as e:
        # Log error but don't break the payment save
        logger.error(
            f"Error updating policy premium_total for payment "
            f"(policy_id={getattr(instance, 'policy_id', 'unknown')}): {e}",
            exc_info=True,
        )
        # Don't re-raise - this is a secondary operation
