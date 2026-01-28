#!/bin/bash

# Local Docker Database Restore Script
# Restores PostgreSQL database in local_postgres container from backup file

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
DB_NAME="insurance_broker_local"
DB_USER="postgres"
CONTAINER_NAME="local_postgres"

BACKUP_FILE="${1}"

echo -e "${GREEN}=== Local Docker Database Restore Script ===${NC}"
echo ""

# Check if backup file is provided
if [ -z "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: No backup file specified${NC}"
    echo "Usage: $0 <backup_file>"
    echo "Example: $0 backups/db_backup_20260127_230003.sql"
    exit 1
fi

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file not found: ${BACKUP_FILE}${NC}"
    exit 1
fi

echo "Backup file: ${BACKUP_FILE}"
BACKUP_SIZE=$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null)
BACKUP_SIZE_MB=$((BACKUP_SIZE / 1024 / 1024))
echo "Backup size: ${BACKUP_SIZE_MB} MB"
echo ""

# Step 1: Check Docker container
echo -e "${YELLOW}[1/5] Checking Docker container...${NC}"
if docker ps --filter "name=${CONTAINER_NAME}" --format "{{.Names}}" | grep -q "${CONTAINER_NAME}"; then
    echo -e "${GREEN}✓ Container ${CONTAINER_NAME} is running${NC}"
else
    echo -e "${RED}✗ Container ${CONTAINER_NAME} is not running${NC}"
    echo "Please start the container first"
    exit 1
fi

# Step 2: Create backup of current database (if exists)
echo -e "${YELLOW}[2/5] Creating backup of current database (if exists)...${NC}"
CURRENT_BACKUP="backups/current_db_backup_$(date +%Y%m%d_%H%M%S).sql"

if docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
    echo "Database exists, creating backup..."
    docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" > "${CURRENT_BACKUP}" 2>/dev/null || true
    if [ -f "${CURRENT_BACKUP}" ] && [ -s "${CURRENT_BACKUP}" ]; then
        echo -e "${GREEN}✓ Current database backed up to: ${CURRENT_BACKUP}${NC}"
    else
        rm -f "${CURRENT_BACKUP}"
        echo -e "${YELLOW}⚠ No existing data to backup${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Database does not exist yet, skipping backup${NC}"
fi

# Step 3: Drop and recreate database
echo -e "${YELLOW}[3/5] Preparing database...${NC}"
echo "Dropping existing database (if exists)..."
docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -c "DROP DATABASE IF EXISTS ${DB_NAME};" 2>/dev/null || true

echo "Creating fresh database..."
docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -c "CREATE DATABASE ${DB_NAME};" 2>/dev/null

echo -e "${GREEN}✓ Database prepared${NC}"

# Step 4: Import backup
echo -e "${YELLOW}[4/5] Importing database backup...${NC}"
echo "This may take a few minutes..."

if docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" < "${BACKUP_FILE}" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Database import completed successfully${NC}"
else
    echo -e "${RED}✗ Database import failed${NC}"
    echo "Check the backup file format and PostgreSQL logs"
    exit 1
fi

# Step 5: Verify imported data
echo -e "${YELLOW}[5/5] Verifying imported data...${NC}"

# Check table count
TABLE_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')

if [ -n "$TABLE_COUNT" ] && [ "$TABLE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Database contains ${TABLE_COUNT} tables${NC}"
else
    echo -e "${RED}✗ No tables found in database${NC}"
    exit 1
fi

# Check Django migrations
MIGRATIONS_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM django_migrations;" 2>/dev/null | tr -d ' ' || echo "0")
echo "  - Django migrations: ${MIGRATIONS_COUNT}"

# Check for key tables
echo "  Checking key tables..."
TABLES_TO_CHECK="auth_user policies_policy clients_client insurers_insurer"
for table in $TABLES_TO_CHECK; do
    if docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM ${table};" > /dev/null 2>&1; then
        ROW_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null | tr -d ' ')
        echo "  - ${table}: ${ROW_COUNT} rows"
    else
        echo "  - ${table}: not found"
    fi
done

# Final message
echo ""
echo -e "${GREEN}=== Restore Complete ===${NC}"
echo "Database: ${DB_NAME}"
echo "Tables: ${TABLE_COUNT}"
echo "Migrations: ${MIGRATIONS_COUNT}"
echo ""
echo "Next steps:"
echo "1. Run Django migrations (if needed):"
echo "   python manage.py migrate"
echo ""
echo "2. Start the development server:"
echo "   python manage.py runserver"
echo ""
if [ -f "$CURRENT_BACKUP" ]; then
    echo -e "${YELLOW}Note: Previous database backup saved to: ${CURRENT_BACKUP}${NC}"
fi
echo -e "${GREEN}Database restore completed successfully!${NC}"
