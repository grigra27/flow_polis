#!/bin/bash
set -e

# Fix ownership of mounted directories so the app user can write to them.
# Runs as root before gosu drop. Handles bind-mounted ./logs whose host
# directory may be owned by root.
chown -R app:app /app/staticfiles /app/media /app/logs 2>/dev/null || true

echo "Waiting for PostgreSQL..."
while ! nc -z $DB_HOST $DB_PORT; do
  sleep 0.1
done
echo "PostgreSQL started"

echo "Running migrations..."
gosu app python manage.py migrate --noinput

echo "Collecting static files..."
gosu app python manage.py collectstatic --noinput --clear

echo "Starting application..."
exec gosu app "$@"
