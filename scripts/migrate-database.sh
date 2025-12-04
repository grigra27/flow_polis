#!/bin/bash

# Database Migration Script - Export from Old Server
# This script exports the database from the old Digital Ocean server
# Requirements: 5.1, 5.2

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
OLD_SERVER_IP="${OLD_SERVER_IP:-64.227.75.233}"
OLD_SERVER_USER="${OLD_SERVER_USER:-root}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="insurance_broker_backup_${TIMESTAMP}.sql"
COMPOSE_FILE="docker-compose.prod.yml"

echo -e "${GREEN}=== Database Migration Script - Export ===${NC}"
echo "Old Server: ${OLD_SERVER_USER}@${OLD_SERVER_IP}"
echo "Backup Directory: ${BACKUP_DIR}"
echo "Backup File: ${BACKUP_FILE}"
echo ""

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Step 1: Check SSH connection to old server
echo -e "${YELLOW}[1/6] Checking SSH connection to old server...${NC}"
if ssh -o ConnectTimeout=10 "${OLD_SERVER_USER}@${OLD_SERVER_IP}" "echo 'SSH connection successful'" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SSH connection successful${NC}"
else
    echo -e "${RED}✗ Failed to connect to old server${NC}"
    echo "Please check:"
    echo "  - Server IP address: ${OLD_SERVER_IP}"
    echo "  - SSH credentials"
    echo "  - Network connectivity"
    exit 1
fi

# Step 2: Check if Docker Compose is running on old server
echo -e "${YELLOW}[2/6] Checking Docker Compose status on old server...${NC}"
if ssh "${OLD_SERVER_USER}@${OLD_SERVER_IP}" "cd ~/insurance_broker && docker-compose -f ${COMPOSE_FILE} ps db | grep -q 'Up'" 2>/dev/null; then
    echo -e "${GREEN}✓ Database container is running${NC}"
else
    echo -e "${RED}✗ Database container is not running${NC}"
    echo "Please ensure the database container is running on the old server"
    exit 1
fi

# Step 3: Get database statistics before export
echo -e "${YELLOW}[3/6] Gathering database statistics...${NC}"
DB_STATS=$(ssh "${OLD_SERVER_USER}@${OLD_SERVER_IP}" "cd ~/insurance_broker && docker-compose -f ${COMPOSE_FILE} exec -T db psql -U postgres -d insurance_broker_prod -t -c \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';\"" 2>/dev/null | tr -d ' ')

if [ -n "$DB_STATS" ] && [ "$DB_STATS" -gt 0 ]; then
    echo -e "${GREEN}✓ Database contains ${DB_STATS} tables${NC}"

    # Get row counts for key tables
    echo "  Checking key tables..."
    MIGRATIONS_COUNT=$(ssh "${OLD_SERVER_USER}@${OLD_SERVER_IP}" "cd ~/insurance_broker && docker-compose -f ${COMPOSE_FILE} exec -T db psql -U postgres -d insurance_broker_prod -t -c \"SELECT COUNT(*) FROM django_migrations;\"" 2>/dev/null | tr -d ' ' || echo "0")
    echo "  - Django migrations: ${MIGRATIONS_COUNT}"

    # Try to get policy count (may fail if table doesn't exist)
    POLICY_COUNT=$(ssh "${OLD_SERVER_USER}@${OLD_SERVER_IP}" "cd ~/insurance_broker && docker-compose -f ${COMPOSE_FILE} exec -T db psql -U postgres -d insurance_broker_prod -t -c \"SELECT COUNT(*) FROM policies_policy;\"" 2>/dev/null | tr -d ' ' || echo "N/A")
    if [ "$POLICY_COUNT" != "N/A" ]; then
        echo "  - Policies: ${POLICY_COUNT}"
    fi
else
    echo -e "${RED}✗ Failed to get database statistics${NC}"
    exit 1
fi

# Step 4: Create database backup on old server
echo -e "${YELLOW}[4/6] Creating database backup on old server...${NC}"
echo "This may take several minutes depending on database size..."

if ssh "${OLD_SERVER_USER}@${OLD_SERVER_IP}" "cd ~/insurance_broker && docker-compose -f ${COMPOSE_FILE} exec -T db pg_dump -U postgres -d insurance_broker_prod --clean --if-exists" > "${BACKUP_DIR}/${BACKUP_FILE}" 2>/dev/null; then
    echo -e "${GREEN}✓ Database backup created successfully${NC}"
else
    echo -e "${RED}✗ Failed to create database backup${NC}"
    exit 1
fi

# Step 5: Verify backup file integrity
echo -e "${YELLOW}[5/6] Verifying backup file integrity...${NC}"

BACKUP_SIZE=$(stat -f%z "${BACKUP_DIR}/${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_DIR}/${BACKUP_FILE}" 2>/dev/null)
BACKUP_SIZE_MB=$((BACKUP_SIZE / 1024 / 1024))

if [ "$BACKUP_SIZE" -gt 1000 ]; then
    echo -e "${GREEN}✓ Backup file size: ${BACKUP_SIZE_MB} MB${NC}"
else
    echo -e "${RED}✗ Backup file seems too small (${BACKUP_SIZE} bytes)${NC}"
    echo "This might indicate an incomplete backup"
    exit 1
fi

# Check if backup contains expected SQL commands
if grep -q "CREATE TABLE" "${BACKUP_DIR}/${BACKUP_FILE}" && grep -q "COPY" "${BACKUP_DIR}/${BACKUP_FILE}"; then
    echo -e "${GREEN}✓ Backup file contains valid SQL commands${NC}"
else
    echo -e "${RED}✗ Backup file does not contain expected SQL commands${NC}"
    exit 1
fi

# Count tables in backup
TABLE_COUNT=$(grep -c "CREATE TABLE" "${BACKUP_DIR}/${BACKUP_FILE}" || echo "0")
echo "  - Tables in backup: ${TABLE_COUNT}"

# Step 6: Create checksum for integrity verification
echo -e "${YELLOW}[6/6] Creating checksum for integrity verification...${NC}"
if command -v md5sum > /dev/null 2>&1; then
    CHECKSUM=$(md5sum "${BACKUP_DIR}/${BACKUP_FILE}" | awk '{print $1}')
    echo "${CHECKSUM}  ${BACKUP_FILE}" > "${BACKUP_DIR}/${BACKUP_FILE}.md5"
    echo -e "${GREEN}✓ Checksum created: ${CHECKSUM}${NC}"
elif command -v md5 > /dev/null 2>&1; then
    CHECKSUM=$(md5 -q "${BACKUP_DIR}/${BACKUP_FILE}")
    echo "${CHECKSUM}  ${BACKUP_FILE}" > "${BACKUP_DIR}/${BACKUP_FILE}.md5"
    echo -e "${GREEN}✓ Checksum created: ${CHECKSUM}${NC}"
else
    echo -e "${YELLOW}⚠ md5sum/md5 not available, skipping checksum${NC}"
fi

# Summary
echo ""
echo -e "${GREEN}=== Export Complete ===${NC}"
echo "Backup file: ${BACKUP_DIR}/${BACKUP_FILE}"
echo "Backup size: ${BACKUP_SIZE_MB} MB"
echo "Tables exported: ${TABLE_COUNT}"
echo ""
echo "Next steps:"
echo "1. Transfer the backup file to the new server:"
echo "   scp ${BACKUP_DIR}/${BACKUP_FILE} root@109.68.215.223:~/insurance_broker/"
echo ""
echo "2. Run the import script on the new server:"
echo "   ./scripts/import-database.sh ${BACKUP_FILE}"
echo ""
echo -e "${YELLOW}Important: Keep this backup file safe until migration is verified!${NC}"
