#!/bin/bash

# setup-telegram.sh
# Script to securely configure Telegram notifications for backups
# This script helps set up Telegram credentials without storing them in version control

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

# Get the absolute path to the application directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

log_info "========================================="
log_info "  Telegram Backup Notifications Setup"
log_info "========================================="
echo ""

log_info "Application directory: $APP_DIR"
echo ""

# Check if .env.prod exists
ENV_FILE="$APP_DIR/.env.prod"

if [ ! -f "$ENV_FILE" ]; then
    log_error ".env.prod file not found at: $ENV_FILE"
    log_error "Please create .env.prod from .env.prod.example first"
    exit 1
fi

log_info "Found .env.prod file"

# Function to update or add environment variable
update_env_var() {
    local var_name="$1"
    local var_value="$2"
    local env_file="$3"

    if grep -q "^${var_name}=" "$env_file"; then
        # Variable exists, update it
        sed -i "s/^${var_name}=.*/${var_name}=${var_value}/" "$env_file"
        log_info "Updated $var_name in $env_file"
    else
        # Variable doesn't exist, add it
        echo "${var_name}=${var_value}" >> "$env_file"
        log_info "Added $var_name to $env_file"
    fi
}

# Interactive setup
echo ""
log_info "Setting up Telegram notifications..."
echo ""

echo "To set up Telegram notifications, you need:"
echo "1. A Telegram bot token (from @BotFather)"
echo "2. A chat or channel ID where notifications will be sent"
echo ""

# Get bot token
echo -n "Enter your Telegram bot token (from @BotFather): "
read -r bot_token

if [ -z "$bot_token" ]; then
    log_error "Bot token cannot be empty"
    exit 1
fi

# Validate bot token format
if [[ ! "$bot_token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    log_warn "Bot token format looks unusual. Expected format: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    echo -n "Continue anyway? (y/n): "
    read -r continue_setup
    if [ "$continue_setup" != "y" ]; then
        log_info "Setup cancelled"
        exit 0
    fi
fi

# Get chat ID
echo -n "Enter your Telegram chat ID (e.g., -1001234567890 for channels): "
read -r chat_id

if [ -z "$chat_id" ]; then
    log_error "Chat ID cannot be empty"
    exit 1
fi

# Ask about enabling notifications
echo -n "Enable Telegram notifications? (y/n) [y]: "
read -r enable_notifications
enable_notifications=${enable_notifications:-y}

if [ "$enable_notifications" = "y" ]; then
    telegram_enabled="true"
else
    telegram_enabled="false"
fi

# Ask about file uploads
echo -n "Enable file uploads to Telegram? (y/n) [y]: "
read -r enable_uploads
enable_uploads=${enable_uploads:-y}

if [ "$enable_uploads" = "y" ]; then
    telegram_upload="true"
else
    telegram_upload="false"
fi

# Ask about file size limit
echo -n "Maximum file size for uploads in MB [45]: "
read -r max_file_size
max_file_size=${max_file_size:-45}

echo ""
log_info "Configuration summary:"
echo "  Bot Token: ${bot_token:0:10}...${bot_token: -10}"
echo "  Chat ID: $chat_id"
echo "  Notifications Enabled: $telegram_enabled"
echo "  File Uploads Enabled: $telegram_upload"
echo "  Max File Size: ${max_file_size}MB"
echo ""

echo -n "Save this configuration? (y/n): "
read -r save_config

if [ "$save_config" != "y" ]; then
    log_info "Configuration not saved"
    exit 0
fi

# Update .env.prod file
log_info "Updating .env.prod file..."

update_env_var "TELEGRAM_BOT_TOKEN" "$bot_token" "$ENV_FILE"
update_env_var "TELEGRAM_CHAT_ID" "$chat_id" "$ENV_FILE"
update_env_var "TELEGRAM_ENABLED" "$telegram_enabled" "$ENV_FILE"
update_env_var "TELEGRAM_UPLOAD_FILES" "$telegram_upload" "$ENV_FILE"
update_env_var "TELEGRAM_MAX_FILE_SIZE" "$max_file_size" "$ENV_FILE"

log_info "Configuration saved successfully!"

# Test the connection
echo ""
log_info "Testing Telegram connection..."

# Source the updated environment
source "$ENV_FILE"
export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_ENABLED TELEGRAM_UPLOAD_FILES TELEGRAM_MAX_FILE_SIZE

# Test connection
if "$SCRIPT_DIR/telegram-notify.sh" test; then
    log_info "✅ Telegram connection test successful!"
    echo ""
    log_info "Setup completed successfully!"
    echo ""
    log_info "Next steps:"
    echo "1. Update your cron jobs to use the Telegram-enabled backup scripts:"
    echo "   - backup-db-telegram.sh instead of backup-db.sh"
    echo "   - backup-media-telegram.sh instead of backup-media.sh"
    echo ""
    echo "2. Test the backup scripts:"
    echo "   ./scripts/backup-db-telegram.sh"
    echo "   ./scripts/backup-media-telegram.sh"
    echo ""
else
    log_error "❌ Telegram connection test failed!"
    log_error "Please check your bot token and chat ID"
    echo ""
    log_info "You can test the connection manually with:"
    echo "  ./scripts/telegram-notify.sh test"
    echo ""
    log_info "Or reconfigure with:"
    echo "  ./scripts/setup-telegram.sh"
fi

echo ""
log_info "========================================="
log_info "  Setup Complete"
log_info "========================================="
