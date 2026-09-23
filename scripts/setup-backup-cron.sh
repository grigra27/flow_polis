#!/bin/bash

# setup-backup-cron.sh
# Script to set up automated backups using cron
# This script configures cron jobs for database and media backups

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get the absolute path to the scripts directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

log_info "========================================="
log_info "  Backup Cron Setup"
log_info "========================================="
echo ""

log_info "Application directory: $APP_DIR"
log_info "Scripts directory: $SCRIPT_DIR"
echo ""

# Check if scripts exist
# P2-06 (2026-09-23): points at the VK/Telegram-integrated scripts, which
# are what production cron actually runs — the plain backup-db.sh/
# backup-media.sh (no status contract, no VK/Telegram delivery, predate
# P0-06..P1-05) have been removed; see docs/BACKUP_RESTORE.md#overview.
if [ ! -f "$SCRIPT_DIR/backup-db-telegram.sh" ]; then
    log_error "backup-db-telegram.sh not found in $SCRIPT_DIR"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/backup-media-telegram.sh" ]; then
    log_error "backup-media-telegram.sh not found in $SCRIPT_DIR"
    exit 1
fi

log_info "Backup scripts found"

# Create cron job entries
CRON_FILE="/tmp/insurance_broker_backup_cron.txt"

cat > "$CRON_FILE" << EOF
# Insurance Broker Application - Automated Backups
# Generated on $(date)

# Database backup - Daily at 2:00 AM
0 2 * * * cd $APP_DIR && $SCRIPT_DIR/backup-db-telegram.sh >> $APP_DIR/logs/backup-db.log 2>&1

# Media files backup - Weekly, Monday at 3:00 AM
0 3 * * 1 cd $APP_DIR && $SCRIPT_DIR/backup-media-telegram.sh >> $APP_DIR/logs/backup-media.log 2>&1

# Cleanup old backups - Weekly, Monday at 4:00 AM
0 4 * * 1 cd $APP_DIR && $SCRIPT_DIR/backup-db-telegram.sh --cleanup >> $APP_DIR/logs/backup-cleanup.log 2>&1
0 4 * * 1 cd $APP_DIR && $SCRIPT_DIR/backup-media-telegram.sh --cleanup >> $APP_DIR/logs/backup-cleanup.log 2>&1

EOF

log_info "Cron configuration created:"
echo ""
cat "$CRON_FILE"
echo ""

# Ask user for confirmation
echo -n "Do you want to install these cron jobs? (yes/no): "
read -r confirmation

if [ "$confirmation" != "yes" ]; then
    log_info "Cron setup cancelled"
    rm -f "$CRON_FILE"
    exit 0
fi

# Create logs directory if it doesn't exist
mkdir -p "$APP_DIR/logs"
log_info "Logs directory ready: $APP_DIR/logs"

# Backup existing crontab
log_info "Backing up existing crontab..."
crontab -l > /tmp/crontab_backup_$(date +%Y%m%d_%H%M%S).txt 2>/dev/null || true

# Add new cron jobs
log_info "Installing cron jobs..."

# Get existing crontab and append new jobs. Strips both the current
# (-telegram) entries, so re-running this script is idempotent, and any
# leftover pre-2026-09-23 entries pointing at the old bare-name scripts.
(crontab -l 2>/dev/null \
    | grep -v "Insurance Broker Application - Automated Backups" \
    | grep -v "backup-db-telegram.sh" \
    | grep -v "backup-media-telegram.sh" \
    | grep -v "backup-db.sh" \
    | grep -v "backup-media.sh"; cat "$CRON_FILE") | crontab -

log_info "Cron jobs installed successfully"

# Clean up
rm -f "$CRON_FILE"

# Display current crontab
echo ""
log_info "Current crontab:"
echo ""
crontab -l | grep -A 10 "Insurance Broker"
echo ""

log_info "========================================="
log_info "  Cron Setup Completed"
log_info "========================================="
echo ""
log_info "Backup schedule:"
log_info "  - Database backup: Daily at 2:00 AM"
log_info "  - Media backup: Weekly, Monday at 3:00 AM"
log_info "  - Cleanup old backups: Weekly, Monday at 4:00 AM"
echo ""
log_info "Logs will be saved to: $APP_DIR/logs/"
echo ""
log_info "To view cron jobs: crontab -l"
log_info "To edit cron jobs: crontab -e"
log_info "To remove cron jobs: crontab -r"
echo ""
