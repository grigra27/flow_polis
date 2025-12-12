#!/bin/bash

# backup-media.sh
# Media files backup script for Insurance Broker application
# Creates timestamped backups of user-uploaded media files

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

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

# Check if media volume exists
check_volume() {
    if ! docker volume ls --format '{{.Name}}' | grep -q "^${MEDIA_VOLUME}$"; then
        log_error "Media volume '$MEDIA_VOLUME' does not exist"
        log_error "Please ensure the application is deployed and volumes are created"
        exit 1
    fi
    log_info "Media volume exists"
}

# Get volume mount point
get_volume_path() {
    local volume_path=$(docker volume inspect "$MEDIA_VOLUME" --format '{{.Mountpoint}}' 2>/dev/null)

    if [ -z "$volume_path" ]; then
        log_error "Could not determine volume mount point"
        return 1
    fi

    echo "$volume_path"
}

# Count files in volume
count_media_files() {
    local volume_path=$1

    # Use a temporary container to count files
    local file_count=$(docker run --rm -v "$MEDIA_VOLUME:/media" alpine sh -c "find /media -type f | wc -l" 2>/dev/null || echo "0")

    echo "$file_count"
}

# Backup media files
backup_media() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/media_backup_${timestamp}.tar.gz"

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

        log_info "Backup completed successfully: $backup_file"
        return 0
    else
        log_error "Backup creation failed"
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

    # Check if file is a valid tar.gz file
    if tar tzf "$backup_file" > /dev/null 2>&1; then
        local file_count=$(tar tzf "$backup_file" 2>/dev/null | wc -l)
        log_info "Backup file integrity verified ($file_count files)"
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
    echo "Media files backup script for Insurance Broker application"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -l, --list              List existing backups"
    echo "  -c, --cleanup           Clean up old backups (older than RETENTION_DAYS)"
    echo "  -v, --verify FILE       Verify backup file integrity"
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
    log_info "  Media Files Backup Process"
    log_info "========================================="
    echo ""

    # Create backup directory
    create_backup_dir

    # Check if volume exists
    check_volume

    # Perform backup
    backup_media || {
        log_error "Backup failed"
        exit 1
    }

    # Verify the backup (skip if empty)
    local latest_backup="$BACKUP_DIR/latest_backup.tar.gz"
    if [ -f "$latest_backup" ]; then
        verify_backup "$latest_backup" || {
            log_warn "Backup verification failed"
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
