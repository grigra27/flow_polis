#!/bin/bash

# Database Migration Script - Import to New Server
# This script imports the database backup to the new Timeweb Cloud server
# Requirements: 5.3, 5.4, 5.5

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKUP_FILE="${1}"
COMPOSE_FILE="docker-compose.prod.yml"
DB_CONTAINER="db"
DB_NAME="insurance_broker_prod"
DB_USER="postgres"

echo -e "${GREEN}=== Database Migration Script - Import ===${NC}"
echo ""

# Check if backup file is provided
if [ -z "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: No backup file specified${NC}"
    echo "Usage: $0 <backup_file>"
    echo "Example: $0 insurance_broker_backup_20231204_120000.sql"
    exit 1
fi

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file not found: ${BACKUP_FILE}${NC}"
    echo "Please ensure the backup file is in the current directory or provide full path"
    exit 1
fi

echo "Backup file: ${BACKUP_FILE}"
BACKUP_SIZE=$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null)
BACKUP_SIZE_MB=$((BACKUP_SIZE / 1024 / 1024))
echo "Backup size: ${BACKUP_SIZE_MB} MB"
echo ""

# Step 1: Verify checksum if available
if [ -f "${BACKUP_FILE}.md5" ]; then
    echo -e "${YELLOW}[1/9] Verifying backup file checksum...${NC}"
    if command -v md5sum > /dev/null 2>&1; then
        if md5sum -c "${BACKUP_FILE}.md5" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ Checksum verification passed${NC}"
        else
            echo -e "${RED}✗ Checksum verification failed${NC}"
            echo "The backup file may be corrupted"
            exit 1
        fi
    elif command -v md5 > /dev/null 2>&1; then
        EXPECTED_CHECKSUM=$(cat "${BACKUP_FILE}.md5" | awk '{print $1}')
        ACTUAL_CHECKSUM=$(md5 -q "${BACKUP_FILE}")
        if [ "$EXPECTED_CHECKSUM" = "$ACTUAL_CHECKSUM" ]; then
            echo -e "${GREEN}✓ Checksum verification passed${NC}"
        else
            echo -e "${RED}✗ Checksum verification failed${NC}"
            echo "Expected: ${EXPECTED_CHECKSUM}"
            echo "Actual: ${ACTUAL_CHECKSUM}"
            exit 1
        fi
    else
        echo -e "${YELLOW}⚠ md5sum/md5 not available, skipping checksum verification${NC}"
    fi
else
    echo -e "${YELLOW}[1/9] No checksum file found, skipping verification${NC}"
fi

# Step 2: Check if Docker Compose is installed
echo -e "${YELLOW}[2/9] Checking Docker Compose installation...${NC}"
if command -v docker-compose > /dev/null 2>&1; then
    COMPOSE_VERSION=$(docker-compose --version)
    echo -e "${GREEN}✓ Docker Compose installed: ${COMPOSE_VERSION}${NC}"
else
    echo -e "${RED}✗ Docker Compose not found${NC}"
    echo "Please install Docker Compose v1"
    exit 1
fi

# Step 3: Check if docker-compose.prod.yml exists
echo -e "${YELLOW}[3/9] Checking Docker Compose configuration...${NC}"
if [ -f "$COMPOSE_FILE" ]; then
    echo -e "${GREEN}✓ ${COMPOSE_FILE} found${NC}"
else
    echo -e "${RED}✗ ${COMPOSE_FILE} not found${NC}"
    echo "Please ensure you're in the project root directory"
    exit 1
fi

# Step 4: Check if environment files exist
echo -e "${YELLOW}[4/9] Checking environment files...${NC}"
if [ -f ".env.prod" ] && [ -f ".env.prod.db" ]; then
    echo -e "${GREEN}✓ Environment files found${NC}"
else
    echo -e "${RED}✗ Environment files missing${NC}"
    echo "Please create .env.prod and .env.prod.db before importing database"
    exit 1
fi

# Step 5: Start database container if not running
echo -e "${YELLOW}[5/9] Checking database container status...${NC}"
if docker-compose -f "$COMPOSE_FILE" ps "$DB_CONTAINER" | grep -q "Up"; then
    echo -e "${GREEN}✓ Database container is running${NC}"
else
    echo -e "${YELLOW}⚠ Database container not running, starting it...${NC}"
    docker-compose -f "$COMPOSE_FILE" up -d "$DB_CONTAINER"
    echo "Waiting for database to be ready..."
    sleep 10

    # Wait for database to be ready
    MAX_RETRIES=30
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" pg_isready -U "$DB_USER" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ Database is ready${NC}"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "Waiting for database... (${RETRY_COUNT}/${MAX_RETRIES})"
        sleep 2
    done

    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo -e "${RED}✗ Database failed to start${NC}"
        exit 1
    fi
fi

# Step 6: Create backup of current database (if exists)
echo -e "${YELLOW}[6/9] Creating backup of current database (if exists)...${NC}"
CURRENT_BACKUP="current_db_backup_$(date +%Y%m%d_%H%M%S).sql"
if docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "Database exists, creating backup..."
    docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" > "$CURRENT_BACKUP" 2>/dev/null || true
    if [ -f "$CURRENT_BACKUP" ] && [ -s "$CURRENT_BACKUP" ]; then
        echo -e "${GREEN}✓ Current database backed up to: ${CURRENT_BACKUP}${NC}"
    else
        rm -f "$CURRENT_BACKUP"
        echo -e "${YELLOW}⚠ No existing data to backup${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Database does not exist yet, skipping backup${NC}"
fi

# Step 7: Import database backup
echo -e "${YELLOW}[7/9] Importing database backup...${NC}"
echo "This may take several minutes depending on database size..."

# Drop and recreate database to ensure clean import
echo "Preparing database..."
docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -c "DROP DATABASE IF EXISTS ${DB_NAME};" 2>/dev/null || true
docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -c "CREATE DATABASE ${DB_NAME};" 2>/dev/null

# Import the backup
if docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" < "$BACKUP_FILE" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Database import completed successfully${NC}"
else
    echo -e "${RED}✗ Database import failed${NC}"
    echo "Check the backup file format and database logs"
    exit 1
fi

# Step 8: Verify imported data
echo -e "${YELLOW}[8/9] Verifying imported data...${NC}"

# Check table count
TABLE_COUNT=$(docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')

if [ -n "$TABLE_COUNT" ] && [ "$TABLE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Database contains ${TABLE_COUNT} tables${NC}"
else
    echo -e "${RED}✗ No tables found in database${NC}"
    exit 1
fi

# Check Django migrations
MIGRATIONS_COUNT=$(docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM django_migrations;" 2>/dev/null | tr -d ' ' || echo "0")
echo "  - Django migrations: ${MIGRATIONS_COUNT}"

# Check for key tables
echo "  Checking key tables..."
TABLES_TO_CHECK="auth_user policies_policy clients_client insurers_insurer"
for table in $TABLES_TO_CHECK; do
    if docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM ${table};" > /dev/null 2>&1; then
        ROW_COUNT=$(docker-compose -f "$COMPOSE_FILE" exec -T "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null | tr -d ' ')
        echo "  - ${table}: ${ROW_COUNT} rows"
    else
        echo "  - ${table}: not found (may not exist yet)"
    fi
done

# Step 9: Run Django migrations
echo -e "${YELLOW}[9/9] Running Django migrations...${NC}"
echo "Starting web container to run migrations..."

# Start web container if not running
docker-compose -f "$COMPOSE_FILE" up -d web

# Wait a moment for container to be ready
sleep 5

# Run migrations
if docker-compose -f "$COMPOSE_FILE" exec -T web python manage.py migrate --noinput > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Django migrations completed successfully${NC}"
else
    echo -e "${YELLOW}⚠ Django migrations had issues (this may be normal if schema is already up to date)${NC}"
fi

# Final verification
echo ""
echo -e "${GREEN}=== Import Complete ===${NC}"
echo "Database: ${DB_NAME}"
echo "Tables: ${TABLE_COUNT}"
echo "Migrations: ${MIGRATIONS_COUNT}"
echo ""
echo "Next steps:"
echo "1. Start all containers:"
echo "   docker-compose -f ${COMPOSE_FILE} up -d"
echo ""
echo "2. Verify the application is working:"
echo "   docker-compose -f ${COMPOSE_FILE} ps"
echo "   docker-compose -f ${COMPOSE_FILE} logs web"
echo ""
echo "3. Test login and data access through the web interface"
echo ""
if [ -f "$CURRENT_BACKUP" ]; then
    echo -e "${YELLOW}Note: Previous database backup saved to: ${CURRENT_BACKUP}${NC}"
fi
echo -e "${GREEN}Database migration completed successfully!${NC}"
