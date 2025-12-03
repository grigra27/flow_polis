#!/bin/bash
set -e

echo "🔧 Fixing migration conflict on server..."

# Remove the old migration record from database
docker-compose -f docker-compose.prod.yml exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB << 'EOSQL'
DELETE FROM django_migrations
WHERE app = 'policies'
  AND name = '0011_alter_paymentschedule_unique_together';
EOSQL

echo "✅ Old migration record removed from database"

# Remove the old migration file if it exists
if [ -f "apps/policies/migrations/0011_alter_paymentschedule_unique_together.py" ]; then
    rm apps/policies/migrations/0011_alter_paymentschedule_unique_together.py
    echo "✅ Old migration file removed"
fi

echo "✅ Migration conflict fixed. Ready to run migrations."
