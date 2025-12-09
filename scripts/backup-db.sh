#!/bin/bash

# backup-db.sh
# PostgreSQL database backup script for Insurance Broker application
# Creates timestamped backups of the PostgreSQL database

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/insurance_broker_backups/database}"
CONTAINER_NAME="${DB_CONTAINER:-insurance_broker_db}"
DB_NAME="${DB_NAME:-insurance_broker_prod}"
DB_USER="${DB_USER:-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Create backup directory
create_backup_dir() {
    if [ ! -d "$BACKUP_DIR" ]; then
        mkdir -p "$BACKUP_DIR"
        log_info "Created backup directory: $BACKUP_DIR"
    fi
}

# Check if database container is running
check_container() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Database container '$CONTAINER_NAME' is not running"
        log_error "Please start the container first: docker-compose -f $COMPOSE_FILE up -d db"
        exit 1
    fi
    log_info "Database container is running"
}

# Perform database backup
backup_database() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/db_backup_${timestamp}.sql"
    local backup_file_gz="${backup_file}.gz"

    log_info "Starting database backup..."
    log_info "Database: $DB_NAME"
    log_info "Backup file: $backup_file_gz"

    # Create backup using pg_dump
    if docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$backup_file"; then
        log_info "Database dump completed successfully"

        # Compress the backup
        log_info "Compressing backup..."
        if gzip "$backup_file"; then
            log_info "Backup compressed successfully"

            # Get file size
            local file_size=$(du -h "$backup_file_gz" | cut -f1)
            log_info "Backup size: $file_size"

            # Create latest symlink
            ln -sf "$(basename "$backup_file_gz")" "$BACKUP_DIR/latest_backup.sql.gz"
            log_info "Created symlink to latest backup"

            # Save backup metadata
            echo "timestamp=$timestamp" > "$BACKUP_DIR/backup_${timestamp}.meta"
            echo "database=$DB_NAME" >> "$BACKUP_DIR/backup_${timestamp}.meta"
            echo "size=$file_size" >> "$BACKUP_DIR/backup_${timestamp}.meta"
            echo "file=$(basename "$backup_file_gz")" >> "$BACKUP_DIR/backup_${timestamp}.meta"

            log_info "Backup completed successfully: $backup_file_gz"
            return 0
        else
            log_error "Failed to compress backup"
            rm -f "$backup_file"
            return 1
        fi
    else
        log_error "Database dump failed"
        rm -f "$backup_file"
        return 1
    fi
}

# Verify backup integrity
verify_backup() {
    local backup_file=$1

    log_info "Verifying backup integrity..."

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi

    # Check if file is a valid gzip file
    if gzip -t "$backup_file" 2>/dev/null; then
        log_info "Backup file integrity verified"
        return 0
    else
        log_error "Backup file is corrupted"
        return 1
    fi
}

# Clean up old backups
cleanup_old_backups() {
    log_info "Cleaning up backups older than $RETENTION_DAYS days..."

    local deleted_count=0

    # Find and delete old backup files
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            rm -f "$file"
            # Also remove metadata file
            local meta_file="${file%.sql.gz}.meta"
            rm -f "$BACKUP_DIR/backup_$(basename "$meta_file")"
            deleted_count=$((deleted_count + 1))
            log_info "Deleted old backup: $(basename "$file")"
        fi
    done < <(find "$BACKUP_DIR" -name "db_backup_*.sql.gz" -type f -mtime +$RETENTION_DAYS)

    if [ $deleted_count -eq 0 ]; then
        log_info "No old backups to clean up"
    else
        log_info "Cleaned up $deleted_count old backup(s)"
    fi
}

# List existing backups
list_backups() {
    log_info "Existing backups in $BACKUP_DIR:"
    echo ""

    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR"/db_backup_*.sql.gz 2>/dev/null)" ]; then
        log_warn "No backups found"
        return
    fi

    printf "%-30s %-15s %-20s\n" "Backup File" "Size" "Date"
    printf "%-30s %-15s %-20s\n" "----------" "----" "----"

    for backup in "$BACKUP_DIR"/db_backup_*.sql.gz; do
        if [ -f "$backup" ]; then
            local filename=$(basename "$backup")
            local size=$(du -h "$backup" | cut -f1)
            local date=$(stat -c %y "$backup" 2>/dev/null || stat -f "%Sm" "$backup" 2>/dev/null || echo "Unknown")
            printf "%-30s %-15s %-20s\n" "$filename" "$size" "${date:0:19}"
        fi
    done
    echo ""
}

# Display usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "PostgreSQL database backup script for Insurance Broker application"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -l, --list              List existing backups"
    echo "  -c, --cleanup           Clean up old backups (older than RETENTION_DAYS)"
    echo "  -v, --verify FILE       Verify backup file integrity"
    echo ""
    echo "Environment Variables:"
    echo "  COMPOSE_FILE            Docker compose file (default: docker-compose.prod.yml)"
    echo "  BACKUP_DIR              Backup directory (default: ~/insurance_broker_backups/database)"
    echo "  DB_CONTAINER            Database container name (default: insurance_broker_db)"
    echo "  DB_NAME                 Database name (default: insurance_broker_prod)"
    echo "  DB_USER                 Database user (default: postgres)"
    echo "  RETENTION_DAYS          Days to keep backups (default: 7)"
    echo ""
    echo "Examples:"
    echo "  $0                      Create a new backup"
    echo "  $0 --list               List all existing backups"
    echo "  $0 --cleanup            Remove backups older than 7 days"
    echo "  RETENTION_DAYS=14 $0    Create backup and keep for 14 days"
    echo ""
}

# Main function
main() {
    # Parse command line arguments
    case "${1:-}" in
        -h|--help)
            usage
            exit 0
            ;;
        -l|--list)
            list_backups
            exit 0
            ;;
        -c|--cleanup)
            create_backup_dir
            cleanup_old_backups
            exit 0
            ;;
        -v|--verify)
            if [ -z "${2:-}" ]; then
                log_error "Please specify a backup file to verify"
                exit 1
            fi
            verify_backup "$2"
            exit $?
            ;;
        "")
            # No arguments - perform backup
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac

    log_info "========================================="
    log_info "  Database Backup Process"
    log_info "========================================="
    echo ""

    # Create backup directory
    create_backup_dir

    # Check if container is running
    check_container

    # Perform backup
    backup_database || {
        log_error "Backup failed"
        exit 1
    }

    # Verify the backup
    local latest_backup="$BACKUP_DIR/latest_backup.sql.gz"
    verify_backup "$latest_backup" || {
        log_warn "Backup verification failed"
    }

    # Clean up old backups
    cleanup_old_backups

    # List current backups
    list_backups

    log_info "========================================="
    log_info "  Backup Process Completed"
    log_info "========================================="

    exit 0
}

# Run main function
main "$@"
