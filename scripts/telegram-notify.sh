#!/bin/bash

# telegram-notify.sh
# Telegram notification functions for backup scripts
# Provides functions to send messages and files to Telegram

# Load Telegram configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/telegram-config.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[TELEGRAM]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[TELEGRAM]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[TELEGRAM]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Check if Telegram is enabled
check_telegram_enabled() {
    if [ "$TELEGRAM_ENABLED" != "true" ]; then
        return 1
    fi

    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
        log_error "Telegram bot token or chat ID not configured"
        return 1
    fi

    return 0
}

# Send text message to Telegram
send_telegram_message() {
    local message="$1"
    local parse_mode="${2:-HTML}"

    if ! check_telegram_enabled; then
        return 0
    fi

    # Escape special characters for HTML
    if [ "$parse_mode" = "HTML" ]; then
        message=$(echo "$message" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
    fi

    local response=$(curl -s -X POST "$TELEGRAM_API_URL/sendMessage" \
        -d "chat_id=$TELEGRAM_CHAT_ID" \
        -d "text=$message" \
        -d "parse_mode=$parse_mode" \
        -d "disable_web_page_preview=true")

    if echo "$response" | grep -q '"ok":true'; then
        log_info "Message sent successfully"
        return 0
    else
        log_error "Failed to send message: $response"
        return 1
    fi
}

# Send file to Telegram
send_telegram_file() {
    local file_path="$1"
    local caption="$2"
    local max_size_mb="$TELEGRAM_MAX_FILE_SIZE"

    if ! check_telegram_enabled; then
        return 0
    fi

    if [ "$TELEGRAM_UPLOAD_FILES" != "true" ]; then
        log_info "File upload disabled in configuration"
        return 0
    fi

    if [ ! -f "$file_path" ]; then
        log_error "File not found: $file_path"
        return 1
    fi

    # Check file size
    local file_size_mb=$(du -m "$file_path" | cut -f1)

    if [ "$file_size_mb" -gt "$max_size_mb" ]; then
        log_warn "File too large for Telegram ($file_size_mb MB > $max_size_mb MB)"

        # Try to compress if it's not already compressed
        if [[ "$file_path" != *.gz ]] && [[ "$file_path" != *.zip ]]; then
            log_info "Attempting to compress file..."
            local compressed_file="${file_path}.gz"

            if gzip -c "$file_path" > "$compressed_file"; then
                local compressed_size_mb=$(du -m "$compressed_file" | cut -f1)

                if [ "$compressed_size_mb" -le "$max_size_mb" ]; then
                    log_info "Compressed file size: $compressed_size_mb MB"
                    file_path="$compressed_file"
                    caption="$caption (compressed)"
                else
                    log_error "Even compressed file is too large ($compressed_size_mb MB)"
                    rm -f "$compressed_file"
                    return 1
                fi
            else
                log_error "Failed to compress file"
                return 1
            fi
        else
            log_error "File is already compressed and too large"
            return 1
        fi
    fi

    log_info "Uploading file: $(basename "$file_path") ($file_size_mb MB)"

    local response=$(curl -s -X POST "$TELEGRAM_API_URL/sendDocument" \
        -F "chat_id=$TELEGRAM_CHAT_ID" \
        -F "document=@$file_path" \
        -F "caption=$caption")

    if echo "$response" | grep -q '"ok":true'; then
        log_info "File uploaded successfully"

        # Clean up temporary compressed file
        if [[ "$file_path" == *.gz ]] && [[ "$caption" == *"compressed"* ]]; then
            rm -f "$file_path"
        fi

        return 0
    else
        log_error "Failed to upload file: $response"

        # Clean up temporary compressed file on failure
        if [[ "$file_path" == *.gz ]] && [[ "$caption" == *"compressed"* ]]; then
            rm -f "$file_path"
        fi

        return 1
    fi
}

# Send backup start notification
notify_backup_start() {
    local backup_type="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S UTC')

    local message="🔄 <b>Backup Started</b>

📋 <b>Type:</b> $backup_type
🕐 <b>Time:</b> $timestamp
🖥 <b>Server:</b> $(hostname)

Starting backup process..."

    send_telegram_message "$message"
}

# Send backup success notification
notify_backup_success() {
    local backup_type="$1"
    local file_path="$2"
    local file_size="$3"
    local duration="$4"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S UTC')

    local message="✅ <b>Backup Completed Successfully</b>

📋 <b>Type:</b> $backup_type
🕐 <b>Completed:</b> $timestamp
📁 <b>File:</b> $(basename "$file_path")
📊 <b>Size:</b> $file_size
⏱ <b>Duration:</b> $duration
🖥 <b>Server:</b> $(hostname)"

    send_telegram_message "$message"

    # Upload file if enabled
    if [ -n "$file_path" ] && [ -f "$file_path" ]; then
        local caption="$backup_type backup - $(basename "$file_path") - $file_size"
        send_telegram_file "$file_path" "$caption"
    fi
}

# Send backup error notification
notify_backup_error() {
    local backup_type="$1"
    local error_message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S UTC')

    local message="❌ <b>Backup Failed</b>

📋 <b>Type:</b> $backup_type
🕐 <b>Time:</b> $timestamp
🖥 <b>Server:</b> $(hostname)
❗ <b>Error:</b> $error_message

Please check the logs for more details."

    send_telegram_message "$message"
}

# Send cleanup notification
notify_cleanup_result() {
    local backup_type="$1"
    local deleted_count="$2"
    local retention_days="$3"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S UTC')

    local message="🧹 <b>Cleanup Completed</b>

📋 <b>Type:</b> $backup_type
🕐 <b>Time:</b> $timestamp
🗑 <b>Deleted:</b> $deleted_count old backup(s)
📅 <b>Retention:</b> $retention_days days
🖥 <b>Server:</b> $(hostname)"

    send_telegram_message "$message"
}

# Test Telegram connection
test_telegram_connection() {
    log_info "Testing Telegram connection..."

    if ! check_telegram_enabled; then
        log_error "Telegram is not enabled or not configured properly"
        return 1
    fi

    local test_message="🧪 <b>Test Message</b>

This is a test message from Insurance Broker backup system.

🕐 <b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S UTC')
🖥 <b>Server:</b> $(hostname)

If you receive this message, Telegram notifications are working correctly! ✅"

    if send_telegram_message "$test_message"; then
        log_info "Telegram connection test successful!"
        return 0
    else
        log_error "Telegram connection test failed!"
        return 1
    fi
}

# Display usage information
usage() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Telegram notification functions for backup scripts"
    echo ""
    echo "Commands:"
    echo "  test                    Test Telegram connection"
    echo "  send MESSAGE            Send a test message"
    echo "  upload FILE [CAPTION]   Upload a test file"
    echo ""
    echo "Examples:"
    echo "  $0 test"
    echo "  $0 send \"Hello from backup system\""
    echo "  $0 upload /path/to/file.txt \"Test file upload\""
    echo ""
}

# Main function for direct script execution
main() {
    case "${1:-}" in
        test)
            test_telegram_connection
            exit $?
            ;;
        send)
            if [ -z "${2:-}" ]; then
                echo "Error: Message text required"
                usage
                exit 1
            fi
            send_telegram_message "$2"
            exit $?
            ;;
        upload)
            if [ -z "${2:-}" ]; then
                echo "Error: File path required"
                usage
                exit 1
            fi
            send_telegram_file "$2" "${3:-Test file upload}"
            exit $?
            ;;
        -h|--help|"")
            usage
            exit 0
            ;;
        *)
            echo "Error: Unknown command: $1"
            usage
            exit 1
            ;;
    esac
}

# Run main function if script is executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
