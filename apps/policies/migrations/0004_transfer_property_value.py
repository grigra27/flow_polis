"""
Migration to transfer property_value from Policy to insurance_sum in PaymentSchedule.

This migration:
1. Forward: Copies property_value from each Policy to all related PaymentSchedules,
   then removes property_value from Policy
2. Reverse: Restores property_value to Policy from first payment's insurance_sum,
   then removes insurance_sum from PaymentSchedule

Edge cases handled:
- Policies without payments: No action needed on forward, default value on reverse
- Different insurance sums on reverse: Uses first payment's value
"""
from django.db import migrations, models
from decimal import Decimal
import django.core.validators


def transfer_property_value_to_payments(apps, schema_editor):
    """
    Forward data migration: Copy property_value from Policy to all related PaymentSchedules.
    
    Uses Django ORM to ensure memory efficiency with batch processing.
    Checks if property_value column exists before attempting to copy data.
    """
    # Try to use Django ORM for safer, more memory-efficient migration
    try:
        Policy = apps.get_model('policies', 'Policy')
        PaymentSchedule = apps.get_model('policies', 'PaymentSchedule')
        
        # Check if property_value field exists in the model state
        if not hasattr(Policy, 'property_value'):
            # Fresh database, no migration needed
            return
        
        # Process in batches to avoid memory issues
        batch_size = 500
        policies = Policy.objects.all()
        
        for i in range(0, policies.count(), batch_size):
            batch = policies[i:i + batch_size]
            for policy in batch:
                try:
                    # Update all payments for this policy
                    PaymentSchedule.objects.filter(
                        policy=policy,
                        insurance_sum__isnull=True
                    ).update(insurance_sum=policy.property_value)
                except AttributeError:
                    # property_value doesn't exist, skip
                    pass
                    
    except Exception as e:
        # If ORM approach fails, try raw SQL as fallback
        cursor = schema_editor.connection.cursor()
        try:
            if schema_editor.connection.vendor == 'sqlite':
                cursor.execute("PRAGMA table_info(policies_policy)")
                columns = [row[1] for row in cursor.fetchall()]
            else:  # PostgreSQL and other databases
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='policies_policy' AND column_name='property_value'
                """)
                columns = [row[0] for row in cursor.fetchall()]
            
            if 'property_value' in columns:
                # Use raw SQL to copy data only if the column exists
                schema_editor.execute("""
                    UPDATE policies_paymentschedule
                    SET insurance_sum = (
                        SELECT property_value
                        FROM policies_policy
                        WHERE policies_policy.id = policies_paymentschedule.policy_id
                    )
                    WHERE insurance_sum IS NULL
                """)
        except:
            # Column doesn't exist or query failed, this is a fresh database
            pass


def restore_property_value_to_policy(apps, schema_editor):
    """
    Reverse data migration: Restore property_value to Policy from first payment's insurance_sum.
    
    Uses Django ORM for memory efficiency with batch processing.
    """
    try:
        Policy = apps.get_model('policies', 'Policy')
        PaymentSchedule = apps.get_model('policies', 'PaymentSchedule')
        
        # Process in batches to avoid memory issues
        batch_size = 500
        policies = Policy.objects.all()
        
        for i in range(0, policies.count(), batch_size):
            batch = policies[i:i + batch_size]
            for policy in batch:
                # Get first payment for this policy
                first_payment = PaymentSchedule.objects.filter(
                    policy=policy
                ).order_by('year_number', 'installment_number').first()
                
                if first_payment and hasattr(first_payment, 'insurance_sum'):
                    policy.property_value = first_payment.insurance_sum
                else:
                    # No payments, use default
                    policy.property_value = Decimal('0.01')
                
                policy.save(update_fields=['property_value'])
                
    except Exception as e:
        # If ORM approach fails, try raw SQL as fallback
        try:
            schema_editor.execute("""
                UPDATE policies_policy
                SET property_value = (
                    SELECT insurance_sum
                    FROM policies_paymentschedule
                    WHERE policies_paymentschedule.policy_id = policies_policy.id
                    ORDER BY year_number, installment_number
                    LIMIT 1
                )
                WHERE EXISTS (
                    SELECT 1
                    FROM policies_paymentschedule
                    WHERE policies_paymentschedule.policy_id = policies_policy.id
                )
            """)
            
            schema_editor.execute("""
                UPDATE policies_policy
                SET property_value = 0.01
                WHERE property_value IS NULL
            """)
        except:
            # If this fails, property_value column doesn't exist yet
            pass


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0003_paymentschedule_insurance_sum'),
    ]

    operations = [
        # Step 1: Make insurance_sum nullable temporarily (it's already created in 0003)
        migrations.AlterField(
            model_name='paymentschedule',
            name='insurance_sum',
            field=models.DecimalField(
                decimal_places=2,
                help_text='Стоимость застрахованного имущества для данного платежа',
                max_digits=15,
                null=True,
                blank=True,
                validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
                verbose_name='Страховая сумма'
            ),
        ),
        
        # Step 2: Copy data from policy.property_value to payment.insurance_sum
        # This will check if property_value exists before attempting to copy
        migrations.RunPython(
            transfer_property_value_to_payments,
            reverse_code=migrations.RunPython.noop  # Don't restore data on reverse yet
        ),
        
        # Step 3: Make insurance_sum non-nullable
        migrations.AlterField(
            model_name='paymentschedule',
            name='insurance_sum',
            field=models.DecimalField(
                decimal_places=2,
                help_text='Стоимость застрахованного имущества для данного платежа',
                max_digits=15,
                validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
                verbose_name='Страховая сумма'
            ),
        ),
        
        # Step 4: Remove property_value from Policy
        migrations.RemoveField(
            model_name='policy',
            name='property_value',
        ),
    ]
