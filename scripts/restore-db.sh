#!/bin/bash

# restore-db.sh
# PostgreSQL database restore script for Insurance Broker application
# Restores database from backup files created by backup-db.sh

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-~/insurance_broker_backups/database}"
CONTAINER_NAME="${DB_CONTAINER:-insurance_broker_db}"
DB_NAME="${DB_NAME:-insurance_broker_prod}"
DB_USER="${DB_USER:-postgres}"

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

# Check if database container is running
check_container() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Database container '$CONTAINER_NAME' is not running"
        log_error "Please start the container first: docker-compose -f $COMPOSE_FILE up -d db"
        exit 1
    fi
    log_info "Database container is running"
}

# List available backups
list_backups() {
    log_info "Available backups in $BACKUP_DIR:"
    echo ""
    
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR"/db_backup_*.sql.gz 2>/dev/null)" ]; then
        log_error "No backups found in $BACKUP_DIR"
        return 1
    fi
    
    local index=1
    declare -g -A backup_files
    
    printf "%-5s %-30s %-15s %-20s\n" "No." "Backup File" "Size" "Date"
    printf "%-5s %-30s %-15s %-20s\n" "---" "----------" "----" "----"
    
    for backup in "$BACKUP_DIR"/db_backup_*.sql.gz; do
        if [ -f "$backup" ]; then
            local filename=$(basename "$backup")
            local size=$(du -h "$backup" | cut -f1)
            local date=$(stat -c %y "$backup" 2>/dev/null || stat -f "%Sm" "$backup" 2>/dev/null || echo "Unknown")
            printf "%-5s %-30s %-15s %-20s\n" "$index" "$filename" "$size" "${date:0:19}"
            backup_files[$index]="$backup"
            index=$((index + 1))
        fi
    done
    echo ""
    
    return 0
}

# Verify backup file
verify_backup() {
    local backup_file=$1
    
    log_info "Verifying backup file..."
    
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

# Create pre-restore backup
create_pre_restore_backup() {
    log_info "Creating pre-restore backup of current database..."
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/pre_restore_backup_${timestamp}.sql"
    local backup_file_gz="${backup_file}.gz"
    
    if docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$backup_file" 2>/dev/null; then
        gzip "$backup_file"
        log_info "Pre-restore backup created: $backup_file_gz"
        echo "$backup_file_gz" > "$BACKUP_DIR/.last_pre_restore_backup"
        return 0
    else
        log_warn "Could not create pre-restore backup (database might be empty)"
        rm -f "$backup_file"
        return 0
    fi
}

# Stop application services
stop_application_services() {
    log_info "Stopping application services..."
    
    # Stop services that depend on the database
    docker-compose -f "$COMPOSE_FILE" stop web celery_worker celery_beat 2>/dev/null || {
        log_warn "Some services could not be stopped"
    }
    
    log_info "Application services stopped"
}

# Start application services
start_application_services() {
    log_info "Starting application services..."
    
    docker-compose -f "$COMPOSE_FILE" up -d web celery_worker celery_beat 2>/dev/null || {
        log_error "Failed to start application services"
        return 1
    }
    
    # Wait for services to be ready
    log_info "Waiting for services to initialize..."
    sleep 10
    
    log_info "Application services started"
}

# Drop and recreate database
drop_and_recreate_database() {
    log_warn "Dropping and recreating database: $DB_NAME"
    
    # Terminate all connections to the database
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" \
        2>/dev/null || true
    
    # Drop database
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" || {
        log_error "Failed to drop database"
        return 1
    }
    
    # Create database
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME;" || {
        log_error "Failed to create database"
        return 1
    }
    
    log_info "Database recreated successfully"
}

# Restore database from backup
restore_database() {
    local backup_file=$1
    
    log_info "Restoring database from: $(basename "$backup_file")"
    
    # Decompress and restore
    if gunzip -c "$backup_file" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" > /dev/null 2>&1; then
        log_info "Database restored successfully"
        return 0
    else
        log_error "Database restore failed"
        return 1
    fi
}

# Verify database after restore
verify_database() {
    log_info "Verifying database after restore..."
    
    # Check if database exists and is accessible
    if docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" > /dev/null 2>&1; then
        log_info "Database is accessible"
        
        # Get table count
        local table_count=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c \
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')
        
        log_info "Database contains $table_count tables"
        
        return 0
    else
        log_error "Database verification failed"
        return 1
    fi
}

# Rollback restore
rollback_restore() {
    log_warn "Rolling back restore operation..."
    
    if [ -f "$BACKUP_DIR/.last_pre_restore_backup" ]; then
        local pre_restore_backup=$(cat "$BACKUP_DIR/.last_pre_restore_backup")
        
        if [ -f "$pre_restore_backup" ]; then
            log_info "Restoring from pre-restore backup..."
            drop_and_recreate_database
            restore_database "$pre_restore_backup" || {
                log_error "Rollback failed"
                return 1
            }
            log_info "Rollback completed successfully"
            return 0
        fi
    fi
    
    log_error "No pre-restore backup found for rollback"
    return 1
}

# Interactive restore
interactive_restore() {
    log_info "========================================="
    log_info "  Interactive Database Restore"
    log_info "========================================="
    echo ""
    
    # List available backups
    list_backups || exit 1
    
    # Prompt user to select backup
    echo -n "Enter backup number to restore (or 'q' to quit): "
    read -r selection
    
    if [ "$selection" = "q" ] || [ "$selection" = "Q" ]; then
        log_info "Restore cancelled by user"
        exit 0
    fi
    
    # Validate selection
    if [ -z "${backup_files[$selection]:-}" ]; then
        log_error "Invalid selection: $selection"
        exit 1
    fi
    
    local backup_file="${backup_files[$selection]}"
    log_info "Selected backup: $(basename "$backup_file")"
    
    # Confirm restore
    echo ""
    log_warn "WARNING: This will replace the current database with the backup!"
    log_warn "Current database: $DB_NAME"
    log_warn "Backup file: $(basename "$backup_file")"
    echo ""
    echo -n "Are you sure you want to continue? (yes/no): "
    read -r confirmation
    
    if [ "$confirmation" != "yes" ]; then
        log_info "Restore cancelled by user"
        exit 0
    fi
    
    # Perform restore
    perform_restore "$backup_file"
}

# Perform restore operation
perform_restore() {
    local backup_file=$1
    
    log_info "========================================="
    log_info "  Starting Database Restore"
    log_info "========================================="
    echo ""
    
    # Verify backup file
    verify_backup "$backup_file" || exit 1
    
    # Create pre-restore backup
    create_pre_restore_backup
    
    # Stop application services
    stop_application_services
    
    # Drop and recreate database
    drop_and_recreate_database || {
        log_error "Failed to prepare database for restore"
        start_application_services
        exit 1
    }
    
    # Restore database
    restore_database "$backup_file" || {
        log_error "Restore failed, attempting rollback..."
        rollback_restore
        start_application_services
        exit 1
    }
    
    # Verify database
    verify_database || {
        log_error "Database verification failed after restore"
        log_warn "You may need to manually check the database"
    }
    
    # Start application services
    start_application_services || {
        log_error "Failed to start application services"
        log_warn "Please start services manually: docker-compose -f $COMPOSE_FILE up -d"
    }
    
    log_info "========================================="
    log_info "  Database Restore Completed"
    log_info "========================================="
    echo ""
    log_info "Database has been restored from: $(basename "$backup_file")"
    log_info "Pre-restore backup saved at: $BACKUP_DIR"
    echo ""
}

# Display usage information
usage() {
    echo "Usage: $0 [OPTIONS] [BACKUP_FILE]"
    echo ""
    echo "PostgreSQL database restore script for Insurance Broker application"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -l, --list              List available backups"
    echo "  -i, --interactive       Interactive restore (select from list)"
    echo "  -f, --file FILE         Restore from specific backup file"
    echo "  --latest                Restore from latest backup"
    echo ""
    echo "Environment Variables:"
    echo "  COMPOSE_FILE            Docker compose file (default: docker-compose.prod.yml)"
    echo "  BACKUP_DIR              Backup directory (default: ~/insurance_broker_backups/database)"
    echo "  DB_CONTAINER            Database container name (default: insurance_broker_db)"
    echo "  DB_NAME                 Database name (default: insurance_broker_prod)"
    echo "  DB_USER                 Database user (default: postgres)"
    echo ""
    echo "Examples:"
    echo "  $0 --interactive        Select backup interactively"
    echo "  $0 --latest             Restore from latest backup"
    echo "  $0 --list               List all available backups"
    echo "  $0 -f backup.sql.gz     Restore from specific file"
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
        -i|--interactive)
            check_container
            interactive_restore
            exit 0
            ;;
        --latest)
            check_container
            local latest_backup="$BACKUP_DIR/latest_backup.sql.gz"
            if [ ! -f "$latest_backup" ]; then
                log_error "Latest backup not found: $latest_backup"
                exit 1
            fi
            perform_restore "$latest_backup"
            exit 0
            ;;
        -f|--file)
            if [ -z "${2:-}" ]; then
                log_error "Please specify a backup file"
                usage
                exit 1
            fi
            check_container
            perform_restore "$2"
            exit 0
            ;;
        "")
            # No arguments - run interactive mode
            check_container
            interactive_restore
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
