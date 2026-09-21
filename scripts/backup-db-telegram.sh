#!/bin/bash

# backup-db-telegram.sh
# PostgreSQL database backup script with Telegram notifications
# Creates timestamped backups of the PostgreSQL database and sends notifications

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Get script directory and load Telegram functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/telegram-notify.sh"
source "$SCRIPT_DIR/backup-status.sh"

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/insurance_broker_backups/database}"
CONTAINER_NAME="${DB_CONTAINER:-insurance_broker_db}"
DB_NAME="${DB_NAME:-insurance_broker_prod}"
DB_USER="${DB_USER:-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
# Lower bound for a credible gzip'd pg_dump; validated again in verify_backup.
MIN_BACKUP_BYTES="${MIN_BACKUP_BYTES:-10240}"
# P0-08 status contract: required stages for DB backups.
# Fallback chain: DB_REQUIRED_STAGES > REQUIRED_STAGES > "created,verified".

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

# Check if database container is running.
# P0-08: pure check — the single final error notification is sent by main().
check_container() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Database container '$CONTAINER_NAME' is not running"
        log_error "Please start the container first: docker-compose -f $COMPOSE_FILE up -d db"
        return 1
    fi
    log_info "Database container is running"
}

# Perform database backup.
# P0-08: no notifications here — success notification was moved to main() and
# happens only AFTER integrity verification (fixes "Completed Successfully →
# Failed" sequencing defect); failure notification likewise belongs to main().
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

            log_info "Backup artifact created: $backup_file_gz"

            echo "$backup_file_gz"  # Return backup file path
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
    echo "  DB_REQUIRED_STAGES      Stages that decide result/exit for DB backups"
    echo "                          (fallback: REQUIRED_STAGES; default: created,verified;"
    echo "                          allowed: created,verified,offsite,notify)"
    echo ""
    echo "Examples:"
    echo "  $0                      Create a new backup"
    echo "  $0 --list               List all existing backups"
    echo "  $0 --cleanup            Remove backups older than 7 days"
    echo "  $0 --test-telegram      Test Telegram notifications"
    echo ""
}

# Main function
#
# P0-08 full-run flow (conceptual state machine):
#   config validation (unknown required stage -> configuration error, exit 1,
#     run aborts before anything is created)
#   → start notification (best effort, never defines status fields)
#   → create            (failure: final error notification, exit 1)
#   → verify            (failure: file preserved, final error notification, exit 2)
#   → offsite stage placeholder (P0: offsite=- / null)
#   → cleanup/list
#   → final success notification + optional file mirror
#   → evaluate result over required stages → last_status.json → BACKUP_RESULT → exit
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

    # Configuration errors abort the run before any backup work (exit 1).
    init_backup_status "db" || exit 1

    log_info "========================================="
    log_info "  Database Backup Process with Telegram"
    log_info "========================================="
    echo ""

    # Send start notification (best effort; outcome not part of status fields)
    notify_backup_start "Database Backup" || true

    # Create backup directory
    create_backup_dir

    # Create stage
    local backup_file=""
    local create_ok=0
    if check_container; then
        if backup_file=$(backup_database); then
            create_ok=1
        fi
    fi

    if [ "$create_ok" -ne 1 ]; then
        STATUS_WORKFLOW_FAIL=1
        notify_backup_error "Database Backup" "Database backup creation failed - check database connectivity and logs"
        STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
        STATUS_MIRROR="-"
        finalize_backup_run
        exit $?
    fi

    STATUS_CREATED=1
    STATUS_FILE="$backup_file"

    # Verify stage.
    # P0-07 semantics preserved: a backup that was created but fails integrity
    # verification exits 2 (creation failure exits 1 above). The file is
    # deliberately preserved for investigation — no rm, retention/cleanup of
    # it is a separate concern.
    if ! verify_backup "$backup_file"; then
        STATUS_WORKFLOW_FAIL=1
        log_error "Backup verification failed"
        notify_backup_error "Database Backup" "Integrity verification failed for $(basename "$backup_file") - file preserved for investigation"
        STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
        STATUS_MIRROR="-"
        finalize_backup_run
        exit $?
    fi
    STATUS_VERIFIED=1

    # Offsite stage placeholder: P0 has no real offsite storage.
    # STATUS_OFFSITE stays "-" (JSON null); messenger delivery must never set it.

    # Provisional core outcome (required stages minus 'notify') is known here,
    # so the FINAL notification can match it: on a core failure (e.g. required
    # offsite, absent at P0) send one error notification instead of
    # "Completed Successfully" + file mirror, keep mirror=- and let the
    # evaluator keep the precedence exit (3 here).
    if ! evaluate_core_result; then
        STATUS_MIRROR="-"
        notify_backup_error "Database Backup" "$(core_failure_reason) for $(basename "$backup_file")"
        STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
        finalize_backup_run
        exit $?
    fi

    # Clean up old backups
    cleanup_old_backups

    # List current backups
    list_backups

    # Final success notification + optional file mirror — only after
    # verification passed (P0-08 sequencing fix).
    local file_size=$(du -h "$backup_file" | cut -f1)
    local duration_formatted="n/a"
    local meta_ts=$(basename "$backup_file" .sql.gz)
    meta_ts="${meta_ts#db_backup_}"
    if [ -f "$BACKUP_DIR/backup_${meta_ts}.meta" ]; then
        duration_formatted=$(awk -F= '$1=="duration"{print $2}' "$BACKUP_DIR/backup_${meta_ts}.meta")
        [ -n "$duration_formatted" ] || duration_formatted="n/a"
    fi
    notify_backup_success "Database Backup" "$backup_file" "$file_size" "$duration_formatted"
    STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
    STATUS_MIRROR=$(map_delivery_tri "${NOTIFY_FILE_RC:-2}")

    finalize_backup_run
    exit $?
}

# Run main function
main "$@"
