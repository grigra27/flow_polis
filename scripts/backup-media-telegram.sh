#!/bin/bash

# backup-media-telegram.sh
# Media files backup script with Telegram notifications
# Creates timestamped backups of user-uploaded media files and sends notifications

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Get script directory and load Telegram functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/telegram-notify.sh"
source "$SCRIPT_DIR/backup-status.sh"
source "$SCRIPT_DIR/backup-retention.sh"

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/insurance_broker_backups/media}"
MEDIA_VOLUME="${MEDIA_VOLUME:-insurance_broker_media_volume}"
# P1-05 (2026-09-23): raised from 7 to 28 days (~4 weekly runs). With no
# offsite store (see P1-01..04, CANCELLED) local retention is the only
# guaranteed safety net.
RETENTION_DAYS="${RETENTION_DAYS:-28}"
# P1-05: floor — cleanup never drops below this many backups regardless
# of age. See scripts/backup-retention.sh.
MIN_RETAINED_BACKUPS="${MIN_RETAINED_BACKUPS:-4}"
# P0-08 status contract: required stages for media backups.
# Fallback chain: MEDIA_REQUIRED_STAGES > REQUIRED_STAGES > "created,verified".

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

# Check if media volume exists.
# P0-08: pure check — the single final error notification is sent by main().
check_volume() {
    if ! docker volume ls --format '{{.Name}}' | grep -q "^${MEDIA_VOLUME}$"; then
        log_error "Media volume '$MEDIA_VOLUME' does not exist"
        log_error "Please ensure the application is deployed and volumes are created"
        return 1
    fi
    log_info "Media volume exists"
}

# Count files in volume
count_media_files() {
    # Use a temporary container to count files (read-only mount: only `find` runs here)
    local file_count=$(docker run --rm -v "$MEDIA_VOLUME:/media:ro" alpine sh -c "find /media -type f | wc -l" 2>/dev/null || echo "0")

    echo "$file_count"
}

# Backup media files.
# P0-08: no notifications here — the success notification moved to main() and
# fires only after integrity verification; the empty-volume path now echoes
# its .empty marker path (it is the backup artifact for that run).
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

        # Create empty backup marker — the P0-08 contract treats a .empty
        # marker written after a confirmed file_count=0 as a correctly created
        # AND correctly verified empty snapshot (no tar verification).
        echo "Empty backup - no media files" > "$BACKUP_DIR/media_backup_${timestamp}.empty"

        echo "$BACKUP_DIR/media_backup_${timestamp}.empty"  # Return marker path
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

        log_info "Backup artifact created: $backup_file"

        echo "$backup_file"  # Return backup file path
        return 0
    else
        log_error "Backup creation failed"
        rm -f "$backup_file"
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
    local retention_days min_retained
    retention_days=$(validate_retention_int "$RETENTION_DAYS" 28 "RETENTION_DAYS")
    min_retained=$(validate_retention_int "$MIN_RETAINED_BACKUPS" 4 "MIN_RETAINED_BACKUPS")

    local dry_run_note=""
    [ "${PRINT_ONLY:-false}" = "true" ] && dry_run_note=" [PRINT_ONLY=true, dry run]"
    log_info "Cleaning up backups older than $retention_days days, keeping at least $min_retained most recent$dry_run_note..."

    # Archives (.tar.gz) and empty-volume markers (.empty) are both backup
    # *runs* for retention purposes — combined into one newest-first list
    # (`ls -t` sorts multiple patterns together) so the floor protects the
    # last N runs regardless of which kind each one is.
    local -a files=()
    while IFS= read -r f; do
        files+=("$BACKUP_DIR/$f")
    done < <(cd "$BACKUP_DIR" && ls -t -- media_backup_*.tar.gz media_backup_*.empty 2>/dev/null)

    local deleted_count
    deleted_count=$(prune_backups "backup" "$min_retained" "$retention_days" "${files[@]}")

    # Sweep .meta sidecars orphaned by a deletion above (only .tar.gz runs
    # have one — .empty markers never do, see backup_media()). Skipped in
    # dry-run: nothing has actually been removed yet.
    if [ "${PRINT_ONLY:-false}" != "true" ]; then
        while IFS= read -r meta; do
            local base_name
            base_name=$(basename "$meta" .meta)
            [ -e "$BACKUP_DIR/media_${base_name}.tar.gz" ] || rm -f "$meta"
        done < <(find "$BACKUP_DIR" -maxdepth 1 -name "backup_*.meta" -type f 2>/dev/null)
    fi

    if [ "$deleted_count" -eq 0 ]; then
        log_info "No old backups to clean up"
    elif [ "${PRINT_ONLY:-false}" = "true" ]; then
        log_info "Would clean up $deleted_count old backup(s) (dry run, nothing deleted)"
    else
        log_info "Cleaned up $deleted_count old backup(s)"
    fi

    # Dry runs are a manual pre-flight check (P1-05 acceptance) — they
    # must not page anyone or touch the real notification channels.
    if [ "${PRINT_ONLY:-false}" = "true" ]; then
        log_info "PRINT_ONLY=true — skipping cleanup notification"
    else
        notify_cleanup_result "Media Backup" "$deleted_count" "$retention_days"
    fi
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
    echo "  -c, --cleanup           Clean up old backups (older than RETENTION_DAYS,"
    echo "                          always keeps at least MIN_RETAINED_BACKUPS;"
    echo "                          PRINT_ONLY=true for a dry run)"
    echo "  -v, --verify FILE       Verify backup file integrity"
    echo "  -t, --test-telegram     Test Telegram connection"
    echo ""
    echo "Environment Variables:"
    echo "  COMPOSE_FILE            Docker compose file (default: docker-compose.prod.yml)"
    echo "  BACKUP_DIR              Backup directory (default: $HOME/insurance_broker_backups/media)"
    echo "  MEDIA_VOLUME            Media volume name (default: insurance_broker_media_volume)"
    echo "  RETENTION_DAYS          Days to keep backups (default: 28)"
    echo "  MIN_RETAINED_BACKUPS    Minimum backups kept regardless of age (default: 4)"
    echo "  PRINT_ONLY              true = dry-run cleanup, log only, delete nothing"
    echo "  MEDIA_REQUIRED_STAGES   Stages that decide result/exit for media backups"
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
#   → create            (failure: final error notification, exit 1;
#                        empty-volume path: .empty marker = created+verified)
#   → verify            (failure: archive preserved, final error notification, exit 2)
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
    init_backup_status "media" || exit 1

    log_info "========================================="
    log_info "  Media Files Backup Process with Telegram"
    log_info "========================================="
    echo ""

    # Send start notification (best effort; outcome not part of status fields)
    notify_backup_start "Media Backup" || true

    local run_start_time=$(date +%s)

    # Create backup directory
    create_backup_dir

    # Create stage
    local backup_file=""
    local create_ok=0
    if check_volume; then
        if backup_file=$(backup_media); then
            create_ok=1
        fi
    fi

    if [ "$create_ok" -ne 1 ]; then
        STATUS_WORKFLOW_FAIL=1
        notify_backup_error "Media Backup" "Media backup creation failed - check volume and logs"
        STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
        STATUS_MIRROR="-"
        finalize_backup_run
        exit $?
    fi

    STATUS_CREATED=1
    STATUS_FILE="$backup_file"

    # Verify stage. Empty-volume flow (P0-08): a .empty marker written after a
    # confirmed file_count=0 is a correctly handled empty snapshot —
    # created=1, verified=1, and it must NOT go through tar verification.
    local is_empty_marker=0
    if [[ "$backup_file" == *.empty ]]; then
        is_empty_marker=1
        STATUS_VERIFIED=1
        log_info "Empty-volume snapshot accepted without tar verification"
    else
        # P0-07 semantics preserved: verification failure exits 2, the archive
        # is deliberately preserved for investigation.
        if ! verify_backup "$backup_file"; then
            STATUS_WORKFLOW_FAIL=1
            log_error "Backup verification failed"
            notify_backup_error "Media Backup" "Integrity verification failed for $(basename "$backup_file") - archive preserved for investigation"
            STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
            STATUS_MIRROR="-"
            finalize_backup_run
            exit $?
        fi
        STATUS_VERIFIED=1
    fi

    # Offsite stage placeholder: P0 has no real offsite storage.
    # STATUS_OFFSITE stays "-" (JSON null); messenger delivery must never set it.

    # Provisional core outcome (required stages minus 'notify') is known here,
    # so the FINAL notification can match it: on a core failure (e.g. required
    # offsite, absent at P0) send one error notification instead of
    # "Completed Successfully" + file mirror, keep mirror=- and let the
    # evaluator keep the precedence exit (3 here).
    if ! evaluate_core_result; then
        STATUS_MIRROR="-"
        notify_backup_error "Media Backup" "$(core_failure_reason) for $(basename "$backup_file")"
        STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
        finalize_backup_run
        exit $?
    fi

    # Clean up old backups
    cleanup_old_backups

    # List current backups
    list_backups

    # Final success notification + optional file mirror — only after the
    # backup outcome is known-good (P0-08 sequencing fix).
    local run_end_time=$(date +%s)
    local run_duration=$((run_end_time - run_start_time))
    local duration_formatted=$(printf "%02d:%02d" $((run_duration/60)) $((run_duration%60)))

    local size_desc
    if [ "$is_empty_marker" -eq 1 ]; then
        size_desc="0 MB (empty)"
    else
        size_desc=$(du -h "$backup_file" | cut -f1)
        local meta_ts=$(basename "$backup_file" .tar.gz)
        meta_ts="${meta_ts#media_backup_}"
        local meta_count=""
        if [ -f "$BACKUP_DIR/backup_${meta_ts}.meta" ]; then
            meta_count=$(awk -F= '$1=="file_count"{print $2}' "$BACKUP_DIR/backup_${meta_ts}.meta")
        fi
        if [ -n "$meta_count" ]; then
            size_desc="$size_desc ($meta_count files)"
        fi
    fi

    notify_backup_success "Media Backup" "$backup_file" "$size_desc" "$duration_formatted"
    STATUS_NOTIFY=$(map_delivery_tri "${NOTIFY_TEXT_RC:-2}")
    STATUS_MIRROR=$(map_delivery_tri "${NOTIFY_FILE_RC:-2}")

    finalize_backup_run
    exit $?
}

# Run main function
main "$@"
