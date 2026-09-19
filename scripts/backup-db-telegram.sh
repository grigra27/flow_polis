#!/bin/bash

# backup-db-telegram.sh
# PostgreSQL database backup script with Telegram notifications
# Creates timestamped backups of the PostgreSQL database and sends notifications

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Get script directory and load Telegram functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/telegram-notify.sh"

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/insurance_broker_backups/database}"
CONTAINER_NAME="${DB_CONTAINER:-insurance_broker_db}"
DB_NAME="${DB_NAME:-insurance_broker_prod}"
DB_USER="${DB_USER:-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
# Lower bound for a credible gzip'd pg_dump; validated again in verify_backup.
MIN_BACKUP_BYTES="${MIN_BACKUP_BYTES:-10240}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
# Contract: stdout of this script's functions captured via command substitution
# must contain only return values (e.g. the backup path from backup_database).
# All status/diagnostic output — including log_* calls made from telegram-notify.sh
# functions sourced above — goes to stderr.
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1" >&2
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
        notify_backup_error "Database Backup" "Database container '$CONTAINER_NAME' is not running"
        exit 1
    fi
    log_info "Database container is running"
}

# Perform database backup
backup_database() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/db_backup_${timestamp}.sql"
    local backup_file_gz="${backup_file}.gz"
    local start_time=$(date +%s)

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

            # Calculate duration
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            local duration_formatted=$(printf "%02d:%02d" $((duration/60)) $((duration%60)))

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
            echo "duration=$duration_formatted" >> "$BACKUP_DIR/backup_${timestamp}.meta"

            log_info "Backup completed successfully: $backup_file_gz"

            # Send success notification
            notify_backup_success "Database Backup" "$backup_file_gz" "$file_size" "$duration_formatted"

            echo "$backup_file_gz"  # Return backup file path
            return 0
        else
            log_error "Failed to compress backup"
            rm -f "$backup_file"
            notify_backup_error "Database Backup" "Failed to compress backup file"
            return 1
        fi
    else
        log_error "Database dump failed"
        rm -f "$backup_file"
        notify_backup_error "Database Backup" "Database dump failed - check database connectivity"
        return 1
    fi
}

# Verify backup integrity — minimal content checks (P0-06), not a restore drill:
#   DB-1  regular file exists and is bigger than MIN_BACKUP_BYTES
#   DB-2  gzip stream is physically intact
#   DB-3  decompressed content starts with the PostgreSQL dump header marker
#   DB-4  the dump ends with the "dump complete" marker (not necessarily the
#         literal last line — pg_dump >= 15.18 appends \unrestrict after it)
# Full decompression into a temp file avoids early-close SIGPIPE failures
# under `set -o pipefail`.
verify_backup() {
    local backup_file=$1

    log_info "Verifying backup integrity..."

    local min_bytes="${MIN_BACKUP_BYTES:-10240}"
    case "$min_bytes" in
        ''|*[!0-9]*)
            log_warn "MIN_BACKUP_BYTES='$min_bytes' is not a non-negative integer, using 10240"
            min_bytes=10240
            ;;
    esac

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi

    local file_bytes
    file_bytes=$(( $(wc -c < "$backup_file") ))
    if [ "$file_bytes" -le "$min_bytes" ]; then
        log_error "Backup file too small: $file_bytes bytes (MIN_BACKUP_BYTES=$min_bytes)"
        return 1
    fi

    # DB-2: valid gzip
    if ! gzip -t "$backup_file" 2>/dev/null; then
        log_error "Backup file is corrupted"
        notify_backup_error "Database Backup" "Backup file integrity check failed - file may be corrupted"
        return 1
    fi

    # DB-3/DB-4: markers in the decompressed stream
    local rc=0
    local dump_file
    dump_file=$(mktemp "${TMPDIR:-/tmp}/verify_pgdump_XXXXXX") || {
        log_error "Cannot create temporary file for verification"
        return 1
    }

    if ! gzip -dc "$backup_file" > "$dump_file"; then
        log_error "Backup file could not be decompressed"
        rm -f "$dump_file"
        return 1
    fi

    # awk (not grep|head pipelines) so no early-close SIGPIPE can fail pipefail,
    # and matching does not depend on the caller's grep aliases/functions
    local header_found
    header_found=$(awk '$0 == "-- PostgreSQL database dump" { print "1"; exit } NR > 10 { exit }' "$dump_file")
    if [ -z "$header_found" ]; then
        log_error "Content is not a PostgreSQL dump: header marker '-- PostgreSQL database dump' missing in the first lines"
        rc=1
    fi

    if [ "$rc" -eq 0 ]; then
        local complete_found
        complete_found=$(awk '
            { buf[NR % 20] = $0 }
            END {
                start = (NR < 20) ? 1 : NR - 19
                for (i = start; i <= NR; i++)
                    if (buf[i % 20] == "-- PostgreSQL database dump complete") { print "1"; exit }
            }' "$dump_file")
        if [ -z "$complete_found" ]; then
            log_error "Dump is incomplete: '-- PostgreSQL database dump complete' marker not found near the end"
            rc=1
        fi
    fi

    rm -f "$dump_file"

    if [ "$rc" -eq 0 ]; then
        log_info "Backup file integrity verified"
    fi
    return $rc
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

    # Send cleanup notification
    notify_cleanup_result "Database Backup" "$deleted_count" "$RETENTION_DAYS"
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
    echo "PostgreSQL database backup script with Telegram notifications"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -l, --list              List existing backups"
    echo "  -c, --cleanup           Clean up old backups (older than RETENTION_DAYS)"
    echo "  -v, --verify FILE       Verify backup file integrity"
    echo "  -t, --test-telegram     Test Telegram connection"
    echo ""
    echo "Environment Variables:"
    echo "  COMPOSE_FILE            Docker compose file (default: docker-compose.prod.yml)"
    echo "  BACKUP_DIR              Backup directory (default: ~/insurance_broker_backups/database)"
    echo "  DB_CONTAINER            Database container name (default: insurance_broker_db)"
    echo "  DB_NAME                 Database name (default: insurance_broker_prod)"
    echo "  DB_USER                 Database user (default: postgres)"
    echo "  RETENTION_DAYS          Days to keep backups (default: 7)"
    echo "  MIN_BACKUP_BYTES        Minimum backup size for verification (default: 10240)"
    echo ""
    echo "Examples:"
    echo "  $0                      Create a new backup"
    echo "  $0 --list               List all existing backups"
    echo "  $0 --cleanup            Remove backups older than 7 days"
    echo "  $0 --test-telegram      Test Telegram notifications"
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
        -t|--test-telegram)
            test_telegram_connection
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
    log_info "  Database Backup Process with Telegram"
    log_info "========================================="
    echo ""

    # Send start notification
    notify_backup_start "Database Backup"

    # Create backup directory
    create_backup_dir

    # Check if container is running
    check_container

    # Perform backup
    local backup_file
    backup_file=$(backup_database) || {
        log_error "Backup failed"
        exit 1
    }

    # Verify the backup.
    # P0-07: a backup that was created but fails integrity verification exits 2
    # (creation failure exits 1 above). The file is deliberately preserved for
    # investigation — no rm, retention/cleanup of it is a separate concern.
    verify_backup "$backup_file" || {
        log_error "Backup verification failed"
        notify_backup_error "Database Backup" "Integrity verification failed for $(basename "$backup_file") - file preserved for investigation"
        exit 2
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
