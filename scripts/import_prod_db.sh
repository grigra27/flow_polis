#!/bin/bash

# Script to import production database to local PostgreSQL
# Скрипт для импорта продакшн базы данных в локальный PostgreSQL

set -e  # Exit on error

PROD_SERVER="root@109.68.215.223"
PROD_APP_DIR="~/insurance_broker"
PROD_CONTAINER="insurance_broker_db"
PROD_DB_NAME="insurance_broker_prod"
PROD_DB_USER="postgres"

LOCAL_CONTAINER="local_postgres"
LOCAL_DB_NAME="insurance_broker_local"
LOCAL_DB_USER="postgres"
LOCAL_DB_PASSWORD="postgres"
LOCAL_PORT="5432"

BACKUP_FILE="db_backup.sql"

echo "=========================================="
echo "Production Database Import Script"
echo "=========================================="
echo ""

# Step 1: Create backup on production server
echo "Step 1: Creating database backup on production server..."
ssh $PROD_SERVER "cd $PROD_APP_DIR && docker exec $PROD_CONTAINER pg_dump -U $PROD_DB_USER $PROD_DB_NAME > $BACKUP_FILE"
echo "✓ Backup created on production server"
echo ""

# Step 2: Download backup to local machine
echo "Step 2: Downloading backup to local machine..."
scp $PROD_SERVER:$PROD_APP_DIR/$BACKUP_FILE ./$BACKUP_FILE
echo "✓ Backup downloaded: ./$BACKUP_FILE"
echo ""

# Step 3: Check if local PostgreSQL container exists
echo "Step 3: Setting up local PostgreSQL..."
if docker ps -a --format '{{.Names}}' | grep -q "^${LOCAL_CONTAINER}$"; then
    echo "Container $LOCAL_CONTAINER already exists"
    if ! docker ps --format '{{.Names}}' | grep -q "^${LOCAL_CONTAINER}$"; then
        echo "Starting existing container..."
        docker start $LOCAL_CONTAINER
    fi
else
    echo "Creating new PostgreSQL container..."
    docker run -d --name $LOCAL_CONTAINER \
        -e POSTGRES_PASSWORD=$LOCAL_DB_PASSWORD \
        -e POSTGRES_DB=$LOCAL_DB_NAME \
        -p $LOCAL_PORT:5432 \
        postgres:15-alpine
    echo "Waiting for PostgreSQL to start..."
    sleep 5
fi
echo "✓ PostgreSQL is running"
echo ""

# Step 4: Drop and recreate database (to ensure clean import)
echo "Step 4: Preparing database for import..."
docker exec $LOCAL_CONTAINER psql -U $LOCAL_DB_USER -c "DROP DATABASE IF EXISTS $LOCAL_DB_NAME;"
docker exec $LOCAL_CONTAINER psql -U $LOCAL_DB_USER -c "CREATE DATABASE $LOCAL_DB_NAME;"
echo "✓ Database prepared"
echo ""

# Step 5: Import backup
echo "Step 5: Importing backup into local database..."
docker exec -i $LOCAL_CONTAINER psql -U $LOCAL_DB_USER $LOCAL_DB_NAME < $BACKUP_FILE
echo "✓ Database imported successfully"
echo ""

# Step 6: Clean up backup file on production server
echo "Step 6: Cleaning up..."
ssh $PROD_SERVER "rm -f $PROD_APP_DIR/$BACKUP_FILE"
echo "✓ Backup file removed from production server"
echo ""

echo "=========================================="
echo "Import completed successfully!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Update your .env file with PostgreSQL settings:"
echo "   DB_NAME=$LOCAL_DB_NAME"
echo "   DB_USER=$LOCAL_DB_USER"
echo "   DB_PASSWORD=$LOCAL_DB_PASSWORD"
echo "   DB_HOST=localhost"
echo "   DB_PORT=$LOCAL_PORT"
echo ""
echo "2. Run your Django application"
echo ""
echo "To switch back to SQLite, just clear DB_NAME in .env"
echo ""
