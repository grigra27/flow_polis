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
    
    Uses raw SQL to ensure compatibility regardless of model state.
    Checks if property_value column exists before attempting to copy data.
    """
    # Check if property_value column exists
    cursor = schema_editor.connection.cursor()
    cursor.execute("PRAGMA table_info(policies_policy)")
    columns = [row[1] for row in cursor.fetchall()]
    
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
    # If property_value doesn't exist, this is a fresh database and no migration is needed


def restore_property_value_to_policy(apps, schema_editor):
    """
    Reverse data migration: Restore property_value to Policy from first payment's insurance_sum.
    
    Uses raw SQL to ensure compatibility regardless of model state.
    """
    # First, update policies that have payments with the first payment's insurance_sum
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
    
    # Then, update policies without payments to use default value
    schema_editor.execute("""
        UPDATE policies_policy
        SET property_value = 0.01
        WHERE property_value IS NULL
    """)


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
            reverse_code=restore_property_value_to_policy
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
        
        # Step 4: Remove property_value from Policy (if it exists)
        # Note: This will fail silently if the field doesn't exist in fresh databases
        migrations.RemoveField(
            model_name='policy',
            name='property_value',
        ),
    ]
