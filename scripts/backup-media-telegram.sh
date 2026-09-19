#!/bin/bash

# backup-media-telegram.sh
# Media files backup script with Telegram notifications
# Creates timestamped backups of user-uploaded media files and sends notifications

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Get script directory and load Telegram functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/telegram-notify.sh"

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/insurance_broker_backups/media}"
MEDIA_VOLUME="${MEDIA_VOLUME:-insurance_broker_media_volume}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
# Contract: stdout of this script's functions captured via command substitution
# must contain only return values (e.g. the backup path from backup_media).
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

# Check if media volume exists
check_volume() {
    if ! docker volume ls --format '{{.Name}}' | grep -q "^${MEDIA_VOLUME}$"; then
        log_error "Media volume '$MEDIA_VOLUME' does not exist"
        log_error "Please ensure the application is deployed and volumes are created"
        notify_backup_error "Media Backup" "Media volume '$MEDIA_VOLUME' does not exist"
        exit 1
    fi
    log_info "Media volume exists"
}

# Count files in volume
count_media_files() {
    # Use a temporary container to count files (read-only mount: only `find` runs here)
    local file_count=$(docker run --rm -v "$MEDIA_VOLUME:/media:ro" alpine sh -c "find /media -type f | wc -l" 2>/dev/null || echo "0")

    echo "$file_count"
}

# Backup media files
backup_media() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/media_backup_${timestamp}.tar.gz"
    local start_time=$(date +%s)

    log_info "Starting media files backup..."
    log_info "Volume: $MEDIA_VOLUME"
    log_info "Backup file: $backup_file"

    # Count files before backup
    local file_count=$(count_media_files)
    log_info "Files to backup: $file_count"

    if [ "$file_count" -eq 0 ]; then
        log_warn "No media files found in volume"
        log_warn "Creating empty backup marker..."

        # Create empty backup marker
        echo "Empty backup - no media files" > "$BACKUP_DIR/media_backup_${timestamp}.empty"

        # Calculate duration
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local duration_formatted=$(printf "%02d:%02d" $((duration/60)) $((duration%60)))

        # Send notification for empty backup
        notify_backup_success "Media Backup" "$BACKUP_DIR/media_backup_${timestamp}.empty" "0 MB (empty)" "$duration_formatted"

        return 0
    fi

    # Create backup using a temporary container
    log_info "Creating backup archive..."

    if docker run --rm \
        -v "$MEDIA_VOLUME:/media:ro" \
        -v "$BACKUP_DIR:/backup" \
        alpine \
        tar czf "/backup/$(basename "$backup_file")" -C /media . 2>/dev/null; then

        log_info "Backup archive created successfully"

        # Calculate duration
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local duration_formatted=$(printf "%02d:%02d" $((duration/60)) $((duration%60)))

        # Get file size
        local file_size=$(du -h "$backup_file" | cut -f1)
        log_info "Backup size: $file_size"

        # Create latest symlink
        ln -sf "$(basename "$backup_file")" "$BACKUP_DIR/latest_backup.tar.gz"
        log_info "Created symlink to latest backup"

        # Save backup metadata
        echo "timestamp=$timestamp" > "$BACKUP_DIR/backup_${timestamp}.meta"
        echo "volume=$MEDIA_VOLUME" >> "$BACKUP_DIR/backup_${timestamp}.meta"
        echo "file_count=$file_count" >> "$BACKUP_DIR/backup_${timestamp}.meta"
        echo "size=$file_size" >> "$BACKUP_DIR/backup_${timestamp}.meta"
        echo "file=$(basename "$backup_file")" >> "$BACKUP_DIR/backup_${timestamp}.meta"
        echo "duration=$duration_formatted" >> "$BACKUP_DIR/backup_${timestamp}.meta"

        log_info "Backup completed successfully: $backup_file"

        # Send success notification
        notify_backup_success "Media Backup" "$backup_file" "$file_size ($file_count files)" "$duration_formatted"

        echo "$backup_file"  # Return backup file path
        return 0
    else
        log_error "Backup creation failed"
        rm -f "$backup_file"
        notify_backup_error "Media Backup" "Failed to create backup archive"
        return 1
    fi
}

# Verify backup integrity — minimal content checks (P0-06), not a restore drill:
#   MEDIA-1  tar.gz reads through without errors (full listing into a temp
#            file — no early-close pipelines under `set -o pipefail`)
#   MEDIA-2  the archive contains at least one regular file
#            (directories/symlinks/hardlinks do not count)
#   MEDIA-3  regular-file count equals `file_count=` in this archive's own
#            backup_<timestamp>.meta (same directory as the archive);
#            missing/ambiguous/malformed metadata is a failure
verify_backup() {
    local backup_file=$1

    log_info "Verifying backup integrity..."

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi

    # MEDIA-1
    local list_file
    list_file=$(mktemp "${TMPDIR:-/tmp}/verify_tarlist_XXXXXX") || {
        log_error "Cannot create temporary file for verification"
        return 1
    }

    if ! tar -tvzf "$backup_file" > "$list_file" 2>/dev/null; then
        log_error "Backup file is corrupted"
        notify_backup_error "Media Backup" "Backup file integrity check failed - file may be corrupted"
        rm -f "$list_file"
        return 1
    fi

    # MEDIA-2: count regular files only ("-" as the leading type character)
    local regular_count
    regular_count=$(awk 'length($0) >= 10 && substr($0, 1, 1) == "-" { c++ } END { print c + 0 }' "$list_file")
    rm -f "$list_file"

    if [ "$regular_count" -eq 0 ]; then
        log_error "Backup archive contains no regular files"
        return 1
    fi

    # MEDIA-3: cross-check with this backup's own metadata
    local base
    base=$(basename "$backup_file")
    case "$base" in
        media_backup_*.tar.gz)
            local ts="${base#media_backup_}"
            ts="${ts%.tar.gz}"
            ;;
        *)
            log_error "Cannot derive metadata file name from archive name: $base"
            return 1
            ;;
    esac
    local meta_file="$(dirname "$backup_file")/backup_${ts}.meta"

    if [ ! -f "$meta_file" ]; then
        log_error "Metadata file not found: $meta_file"
        return 1
    fi

    local declared declared_n declared_value
    declared=$(awk '/^file_count=/ { print }' "$meta_file")
    declared_n=$(printf '%s\n' "$declared" | awk 'length($0) > 0 { c++ } END { print c + 0 }')

    if [ "$declared_n" -eq 0 ]; then
        log_error "Metadata $meta_file has no file_count= entry"
        return 1
    fi
    if [ "$declared_n" -gt 1 ]; then
        log_error "Metadata $meta_file has $declared_n file_count= entries (ambiguous)"
        return 1
    fi

    declared_value=$(printf '%s' "$declared" | sed -e 's/^file_count=//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    case "$declared_value" in
        ''|*[!0-9]*)
            log_error "Metadata file_count is not a non-negative integer: '$declared_value'"
            return 1
            ;;
    esac

    if [ "$declared_value" -eq 0 ]; then
        log_error "Metadata file_count=0 for a real .tar.gz archive (empty volumes use the .empty marker path and are not verified here)"
        return 1
    fi

    if [ "$regular_count" -ne "$declared_value" ]; then
        log_error "Regular file count mismatch: archive has $regular_count, metadata file_count=$declared_value"
        return 1
    fi

    log_info "Backup file integrity verified ($regular_count files)"
    return 0
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
            local base_name=$(basename "$file" .tar.gz)
            local meta_file="$BACKUP_DIR/${base_name#media_}.meta"
            rm -f "$meta_file"
            deleted_count=$((deleted_count + 1))
            log_info "Deleted old backup: $(basename "$file")"
        fi
    done < <(find "$BACKUP_DIR" -name "media_backup_*.tar.gz" -type f -mtime +$RETENTION_DAYS)

    # Also clean up empty backup markers
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            rm -f "$file"
            deleted_count=$((deleted_count + 1))
            log_info "Deleted old empty backup marker: $(basename "$file")"
        fi
    done < <(find "$BACKUP_DIR" -name "media_backup_*.empty" -type f -mtime +$RETENTION_DAYS)

    if [ $deleted_count -eq 0 ]; then
        log_info "No old backups to clean up"
    else
        log_info "Cleaned up $deleted_count old backup(s)"
    fi

    # Send cleanup notification
    notify_cleanup_result "Media Backup" "$deleted_count" "$RETENTION_DAYS"
}

# List existing backups
list_backups() {
    log_info "Existing backups in $BACKUP_DIR:"
    echo ""

    if [ ! -d "$BACKUP_DIR" ]; then
        log_warn "Backup directory does not exist"
        return
    fi

    local has_backups=false

    printf "%-35s %-15s %-20s %-10s\n" "Backup File" "Size" "Date" "Files"
    printf "%-35s %-15s %-20s %-10s\n" "----------" "----" "----" "-----"

    for backup in "$BACKUP_DIR"/media_backup_*.tar.gz; do
        if [ -f "$backup" ]; then
            has_backups=true
            local filename=$(basename "$backup")
            local size=$(du -h "$backup" | cut -f1)
            local date=$(stat -c %y "$backup" 2>/dev/null || stat -f "%Sm" "$backup" 2>/dev/null || echo "Unknown")

            # Try to get file count from metadata
            local timestamp=$(echo "$filename" | sed 's/media_backup_\(.*\)\.tar\.gz/\1/')
            local meta_file="$BACKUP_DIR/backup_${timestamp}.meta"
            local file_count="N/A"

            if [ -f "$meta_file" ]; then
                file_count=$(grep "^file_count=" "$meta_file" | cut -d= -f2)
            fi

            printf "%-35s %-15s %-20s %-10s\n" "$filename" "$size" "${date:0:19}" "$file_count"
        fi
    done

    # Check for empty backup markers
    for marker in "$BACKUP_DIR"/media_backup_*.empty; do
        if [ -f "$marker" ]; then
            has_backups=true
            local filename=$(basename "$marker")
            local date=$(stat -c %y "$marker" 2>/dev/null || stat -f "%Sm" "$marker" 2>/dev/null || echo "Unknown")
            printf "%-35s %-15s %-20s %-10s\n" "$filename" "0" "${date:0:19}" "0"
        fi
    done

    if [ "$has_backups" = false ]; then
        log_warn "No backups found"
    fi

    echo ""
}

# Display usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Media files backup script with Telegram notifications"
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
    echo "  BACKUP_DIR              Backup directory (default: $HOME/insurance_broker_backups/media)"
    echo "  MEDIA_VOLUME            Media volume name (default: insurance_broker_media_volume)"
    echo "  RETENTION_DAYS          Days to keep backups (default: 7)"
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
    log_info "  Media Files Backup Process with Telegram"
    log_info "========================================="
    echo ""

    # Send start notification
    notify_backup_start "Media Backup"

    # Create backup directory
    create_backup_dir

    # Check if volume exists
    check_volume

    # Perform backup
    local backup_file
    backup_file=$(backup_media) || {
        log_error "Backup failed"
        exit 1
    }

    # Verify the backup (skipped for the .empty marker path — an empty volume
    # is a normal success scenario, not a verification failure).
    # P0-07: a backup that was created but fails integrity verification exits 2
    # (creation failure exits 1 above). The archive is deliberately preserved
    # for investigation — no rm, retention/cleanup of it is a separate concern.
    if [ -f "$backup_file" ] && [[ "$backup_file" == *.tar.gz ]]; then
        verify_backup "$backup_file" || {
            log_error "Backup verification failed"
            notify_backup_error "Media Backup" "Integrity verification failed for $(basename "$backup_file") - archive preserved for investigation"
            exit 2
        }
    fi

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
