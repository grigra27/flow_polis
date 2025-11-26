#!/bin/bash
# Safe migration script with automatic rollback on failure
# This script attempts to run migrations and rolls back if they fail

set -e

echo "🔍 Checking current migration status..."
python manage.py showmigrations policies

echo ""
echo "📊 Checking database size and memory..."
python manage.py shell << 'PYTHON'
from apps.policies.models import Policy, PaymentSchedule
from django.db import connection

policy_count = Policy.objects.count()
payment_count = PaymentSchedule.objects.count()

print(f"Policies in database: {policy_count}")
print(f"Payments in database: {payment_count}")
print(f"Estimated memory needed: ~{(policy_count + payment_count) * 0.001:.2f} MB")

# Check if property_value column exists
with connection.cursor() as cursor:
    if connection.vendor == 'postgresql':
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='policies_policy' AND column_name='property_value'
        """)
        has_property_value = len(cursor.fetchall()) > 0
    else:
        cursor.execute("PRAGMA table_info(policies_policy)")
        columns = [row[1] for row in cursor.fetchall()]
        has_property_value = 'property_value' in columns
    
    print(f"property_value column exists: {has_property_value}")
PYTHON

echo ""
echo "🚀 Starting migration..."
echo "This may take a while for large databases..."

# Try to run migrations with timeout
timeout 300 python manage.py migrate policies || {
    echo "❌ Migration failed or timed out!"
    echo "🔄 Attempting to rollback to previous state..."
    
    # Try to rollback to migration 0002
    python manage.py migrate policies 0002 || {
        echo "❌ Rollback failed!"
        echo "⚠️  Manual intervention required"
        exit 1
    }
    
    echo "✅ Rollback successful"
    echo "💡 Suggestions:"
    echo "   1. Check server memory (free -h)"
    echo "   2. Consider running migration during low-traffic period"
    echo "   3. Check PostgreSQL logs for errors"
    exit 1
}

echo ""
echo "✅ Migration completed successfully!"
echo "🔍 Verifying migration..."

python manage.py shell << 'PYTHON'
from apps.policies.models import PaymentSchedule
from django.db import connection

# Check if insurance_sum column exists
with connection.cursor() as cursor:
    if connection.vendor == 'postgresql':
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='policies_paymentschedule' AND column_name='insurance_sum'
        """)
        has_insurance_sum = len(cursor.fetchall()) > 0
    else:
        cursor.execute("PRAGMA table_info(policies_paymentschedule)")
        columns = [row[1] for row in cursor.fetchall()]
        has_insurance_sum = 'insurance_sum' in columns
    
    print(f"✅ insurance_sum column exists: {has_insurance_sum}")
    
    if has_insurance_sum:
        # Check if data was migrated
        null_count = PaymentSchedule.objects.filter(insurance_sum__isnull=True).count()
        total_count = PaymentSchedule.objects.count()
        print(f"✅ Payments with insurance_sum: {total_count - null_count}/{total_count}")
        
        if null_count > 0:
            print(f"⚠️  Warning: {null_count} payments have NULL insurance_sum")
PYTHON

echo ""
echo "🎉 Migration verification complete!"
