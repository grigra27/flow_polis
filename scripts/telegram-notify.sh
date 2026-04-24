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

# Check if VK mirroring is enabled/configured
check_vk_enabled() {
    local silent="${1:-false}"

    if [ "${VK_ENABLED:-false}" != "true" ]; then
        if [ "$silent" != "true" ]; then
            log_error "VK mirroring is disabled (VK_ENABLED=false)"
        fi
        return 1
    fi

    if [ -z "${VK_COMMUNITY_TOKEN:-}" ] || [ -z "${VK_USER_ID:-}" ]; then
        if [ "$silent" != "true" ]; then
            log_error "VK mirroring is not configured (VK_COMMUNITY_TOKEN or VK_USER_ID missing)"
        fi
        return 1
    fi

    return 0
}

# Extract JSON field by dot path using python3 (supports dicts/lists).
# Example paths: response.upload_url, response.0.id
json_extract_field() {
    local path="$1"

    if ! command -v python3 >/dev/null 2>&1; then
        return 1
    fi

    python3 -c '
import json
import sys

path = sys.argv[1].split(".")
raw = sys.stdin.read()
if not raw:
    sys.exit(1)

try:
    obj = json.loads(raw)
except Exception:
    sys.exit(1)

for segment in path:
    if isinstance(obj, list):
        try:
            obj = obj[int(segment)]
        except Exception:
            sys.exit(1)
    elif isinstance(obj, dict):
        if segment not in obj:
            sys.exit(1)
        obj = obj[segment]
    else:
        sys.exit(1)

if obj is None:
    sys.exit(1)

if isinstance(obj, (dict, list)):
    print(json.dumps(obj, ensure_ascii=False))
else:
    print(obj)
' "$path"
}

# Send mirrored text message to VK (same text as Telegram)
send_vk_mirror_message() {
    local message="$1"

    if ! check_vk_enabled; then
        return 1
    fi

    # random_id is required by VK API to deduplicate messages
    local random_id="${RANDOM}$(date +%s)"
    local response=$(curl -s -X POST "https://api.vk.com/method/messages.send" \
        --data-urlencode "user_id=$VK_USER_ID" \
        --data-urlencode "message=$message" \
        --data-urlencode "random_id=$random_id" \
        --data-urlencode "access_token=$VK_COMMUNITY_TOKEN" \
        --data-urlencode "v=5.199")

    if echo "$response" | grep -q '"response"'; then
        log_info "Message mirrored to VK successfully"
        return 0
    else
        log_error "Failed to mirror message to VK: $response"
        return 1
    fi
}

# Upload file to VK docs and send it to configured user with caption.
send_vk_file() {
    local file_path="$1"
    local caption="${2:-Backup file}"

    if ! check_vk_enabled; then
        return 1
    fi

    if [ ! -f "$file_path" ]; then
        log_error "VK file mirror failed: file not found: $file_path"
        return 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        log_error "VK file mirror requires python3 for JSON parsing"
        return 1
    fi

    local file_name
    file_name="$(basename "$file_path")"

    # 1) Get VK upload URL for message docs
    local upload_server_response
    upload_server_response=$(curl -s -X POST "https://api.vk.com/method/docs.getMessagesUploadServer" \
        --data-urlencode "peer_id=$VK_USER_ID" \
        --data-urlencode "type=doc" \
        --data-urlencode "access_token=$VK_COMMUNITY_TOKEN" \
        --data-urlencode "v=5.199")

    if echo "$upload_server_response" | grep -q '"error"'; then
        log_error "VK docs.getMessagesUploadServer error: $upload_server_response"
        return 1
    fi

    local upload_url
    upload_url=$(printf '%s' "$upload_server_response" | json_extract_field "response.upload_url" 2>/dev/null || true)
    if [ -z "$upload_url" ]; then
        log_error "VK upload URL not found in response: $upload_server_response"
        return 1
    fi

    # 2) Upload file bytes
    local upload_response
    upload_response=$(curl -s -X POST "$upload_url" -F "file=@$file_path")
    if echo "$upload_response" | grep -q '"error"'; then
        log_error "VK upload file error: $upload_response"
        return 1
    fi

    local file_token
    file_token=$(printf '%s' "$upload_response" | json_extract_field "file" 2>/dev/null || true)
    if [ -z "$file_token" ]; then
        log_error "VK upload token not found in response: $upload_response"
        return 1
    fi

    # 3) Save uploaded file as VK document
    local save_response
    save_response=$(curl -s -X POST "https://api.vk.com/method/docs.save" \
        --data-urlencode "file=$file_token" \
        --data-urlencode "title=$file_name" \
        --data-urlencode "access_token=$VK_COMMUNITY_TOKEN" \
        --data-urlencode "v=5.199")

    if echo "$save_response" | grep -q '"error"'; then
        log_error "VK docs.save error: $save_response"
        return 1
    fi

    local owner_id
    local doc_id
    owner_id=$(printf '%s' "$save_response" | json_extract_field "response.0.owner_id" 2>/dev/null || true)
    doc_id=$(printf '%s' "$save_response" | json_extract_field "response.0.id" 2>/dev/null || true)

    # VK API may return docs.save result in object form: response.doc.{owner_id,id}
    if [ -z "$owner_id" ] || [ -z "$doc_id" ]; then
        owner_id=$(printf '%s' "$save_response" | json_extract_field "response.doc.owner_id" 2>/dev/null || true)
        doc_id=$(printf '%s' "$save_response" | json_extract_field "response.doc.id" 2>/dev/null || true)
    fi

    if [ -z "$owner_id" ] || [ -z "$doc_id" ]; then
        log_error "VK document identifiers not found in response: $save_response"
        return 1
    fi

    local attachment="doc${owner_id}_${doc_id}"
    local random_id="${RANDOM}$(date +%s)"

    # 4) Send saved document to target user
    local send_response
    send_response=$(curl -s -X POST "https://api.vk.com/method/messages.send" \
        --data-urlencode "user_id=$VK_USER_ID" \
        --data-urlencode "message=$caption" \
        --data-urlencode "attachment=$attachment" \
        --data-urlencode "random_id=$random_id" \
        --data-urlencode "access_token=$VK_COMMUNITY_TOKEN" \
        --data-urlencode "v=5.199")

    if echo "$send_response" | grep -q '"response"'; then
        log_info "File mirrored to VK successfully"
        return 0
    fi

    log_error "VK messages.send (with attachment) failed: $send_response"
    return 1
}

# Send text message only to Telegram
send_telegram_message_only() {
    local message="$1"
    local parse_mode="${2:-}"

    if ! check_telegram_enabled; then
        return 1
    fi

    # Use simple text format to avoid HTML parsing issues
    local response
    # Force IPv4 to avoid intermittent IPv6 routing issues in some Docker hosts.
    response=$(curl -4 -sS --connect-timeout 15 --max-time 60 --retry 2 --retry-delay 2 --retry-connrefused -X POST "$TELEGRAM_API_URL/sendMessage" \
        -d "chat_id=$TELEGRAM_CHAT_ID" \
        -d "text=$message" \
        -d "disable_web_page_preview=true" 2>&1)
    local curl_exit=$?

    if [ $curl_exit -ne 0 ]; then
        log_error "curl sendMessage failed (exit: $curl_exit): $response"
        return 1
    fi

    if echo "$response" | grep -q '"ok":true'; then
        log_info "Message sent successfully"
        return 0
    else
        log_error "Failed to send message: $response"
        return 1
    fi
}

# Send file only to Telegram
send_telegram_file_only() {
    local file_path="$1"
    local caption="$2"
    local max_size_mb="$TELEGRAM_MAX_FILE_SIZE"

    if ! check_telegram_enabled; then
        return 1
    fi

    if [ "$TELEGRAM_UPLOAD_FILES" != "true" ]; then
        log_warn "Telegram file upload disabled in configuration"
        return 1
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

    local response
    # Force IPv4 to avoid intermittent IPv6 routing issues in some Docker hosts.
    response=$(curl -4 -sS --connect-timeout 20 --max-time 300 --retry 3 --retry-delay 2 --retry-connrefused -X POST "$TELEGRAM_API_URL/sendDocument" \
        -F "chat_id=$TELEGRAM_CHAT_ID" \
        -F "document=@$file_path" \
        --form-string "caption=$caption" 2>&1)
    local curl_exit=$?

    if [ $curl_exit -ne 0 ]; then
        log_error "curl sendDocument failed (exit: $curl_exit): $response"

        # Clean up temporary compressed file on failure
        if [[ "$file_path" == *.gz ]] && [[ "$caption" == *"compressed"* ]]; then
            rm -f "$file_path"
        fi

        return 1
    fi

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

# Send text message to all configured channels in parallel.
# Return 0 if at least one channel succeeded.
send_telegram_message() {
    local message="$1"
    local tg_pid=""
    local vk_pid=""
    local tg_status=1
    local vk_status=1
    local tg_enabled=0
    local vk_enabled=0

    if check_telegram_enabled; then
        tg_enabled=1
        send_telegram_message_only "$message" &
        tg_pid=$!
    fi

    if check_vk_enabled true; then
        vk_enabled=1
        send_vk_mirror_message "$message" &
        vk_pid=$!
    fi

    if [ "$tg_enabled" -eq 0 ] && [ "$vk_enabled" -eq 0 ]; then
        log_warn "No enabled notification channels for message send"
        return 0
    fi

    if [ -n "$tg_pid" ]; then
        wait "$tg_pid"
        tg_status=$?
    fi

    if [ -n "$vk_pid" ]; then
        wait "$vk_pid"
        vk_status=$?
    fi

    if [ "$tg_enabled" -eq 1 ] && [ "$tg_status" -eq 0 ]; then
        return 0
    fi

    if [ "$vk_enabled" -eq 1 ] && [ "$vk_status" -eq 0 ]; then
        return 0
    fi

    log_warn "Message delivery failed on all enabled channels"
    return 1
}

# Send file to all configured channels in parallel.
# Return 0 if at least one channel succeeded.
send_telegram_file() {
    local file_path="$1"
    local caption="$2"
    local tg_pid=""
    local vk_pid=""
    local tg_status=1
    local vk_status=1
    local tg_enabled=0
    local vk_enabled=0

    if check_telegram_enabled && [ "$TELEGRAM_UPLOAD_FILES" = "true" ]; then
        tg_enabled=1
        send_telegram_file_only "$file_path" "$caption" &
        tg_pid=$!
    fi

    if check_vk_enabled true; then
        vk_enabled=1
        send_vk_file "$file_path" "$caption" &
        vk_pid=$!
    fi

    if [ "$tg_enabled" -eq 0 ] && [ "$vk_enabled" -eq 0 ]; then
        log_warn "No enabled notification channels for file upload"
        return 0
    fi

    if [ -n "$tg_pid" ]; then
        wait "$tg_pid"
        tg_status=$?
    fi

    if [ -n "$vk_pid" ]; then
        wait "$vk_pid"
        vk_status=$?
    fi

    if [ "$tg_enabled" -eq 1 ] && [ "$tg_status" -eq 0 ]; then
        return 0
    fi

    if [ "$vk_enabled" -eq 1 ] && [ "$vk_status" -eq 0 ]; then
        return 0
    fi

    log_warn "File delivery failed on all enabled channels"
    return 1
}

# Send backup start notification
notify_backup_start() {
    local backup_type="$1"
    local timestamp=$(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')

    local message="🔄 Backup Started

📋 Type: $backup_type
🕐 Time: $timestamp
🖥 Server: $(hostname)

Starting backup process..."

    send_telegram_message "$message" || true
}

# Send backup success notification
notify_backup_success() {
    local backup_type="$1"
    local file_path="$2"
    local file_size="$3"
    local duration="$4"
    local timestamp=$(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')

    local message="✅ Backup Completed Successfully

📋 Type: $backup_type
🕐 Completed: $timestamp
📁 File: $(basename "$file_path")
📊 Size: $file_size
⏱ Duration: $duration
🖥 Server: $(hostname)"

    send_telegram_message "$message" || true

    # Upload file if enabled
    if [ -n "$file_path" ] && [ -f "$file_path" ]; then
        local caption="$backup_type backup - $(basename "$file_path") - $file_size"
        send_telegram_file "$file_path" "$caption" || true
    fi
}

# Send backup error notification
notify_backup_error() {
    local backup_type="$1"
    local error_message="$2"
    local timestamp=$(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')

    local message="❌ Backup Failed

📋 Type: $backup_type
🕐 Time: $timestamp
🖥 Server: $(hostname)
❗ Error: $error_message

Please check the logs for more details."

    send_telegram_message "$message" || true
}

# Send cleanup notification
notify_cleanup_result() {
    local backup_type="$1"
    local deleted_count="$2"
    local retention_days="$3"
    local timestamp=$(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')

    local message="🧹 Cleanup Completed

📋 Type: $backup_type
🕐 Time: $timestamp
🗑 Deleted: $deleted_count old backup(s)
📅 Retention: $retention_days days
🖥 Server: $(hostname)"

    send_telegram_message "$message" || true
}

# Test Telegram connection
test_telegram_connection() {
    log_info "Testing Telegram connection..."

    if ! check_telegram_enabled; then
        log_error "Telegram is not enabled or not configured properly"
        return 1
    fi

    local test_message="🧪 Test Message

This is a test message from Insurance Broker backup system.

🕐 Time: $(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')
🖥 Server: $(hostname)

If you receive this message, Telegram notifications are working correctly! ✅"

    if send_telegram_message_only "$test_message"; then
        log_info "Telegram connection test successful!"
        return 0
    else
        log_error "Telegram connection test failed!"
        return 1
    fi
}

# Test VK connection
test_vk_connection() {
    log_info "Testing VK connection..."

    if ! check_vk_enabled; then
        log_error "VK is not enabled or not configured properly"
        return 1
    fi

    local test_message="🧪 Test Message

This is a test message from Insurance Broker backup system.

🕐 Time: $(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')
🖥 Server: $(hostname)

If you receive this message, VK notifications are working correctly! ✅"

    if send_vk_mirror_message "$test_message"; then
        log_info "VK connection test successful!"
        return 0
    else
        log_error "VK connection test failed!"
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
    echo "  test                    Test Telegram-only connection"
    echo "  vk-test                 Test VK-only connection"
    echo "  send MESSAGE            Send message in parallel (Telegram + VK)"
    echo "  upload FILE [CAPTION]   Upload file in parallel (Telegram + VK)"
    echo "  vk-send MESSAGE         Send message only to VK"
    echo "  vk-upload FILE [CAPTION] Upload file only to VK"
    echo ""
    echo "Examples:"
    echo "  $0 test"
    echo "  $0 vk-test"
    echo "  $0 send \"Hello from backup system\""
    echo "  $0 upload /path/to/file.txt \"Test file upload\""
    echo "  $0 vk-send \"VK only test\""
    echo "  $0 vk-upload /path/to/file.txt \"VK only upload\""
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
        vk-test)
            test_vk_connection
            exit $?
            ;;
        vk-send)
            if [ -z "${2:-}" ]; then
                echo "Error: Message text required"
                usage
                exit 1
            fi
            send_vk_mirror_message "$2"
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
        vk-upload)
            if [ -z "${2:-}" ]; then
                echo "Error: File path required"
                usage
                exit 1
            fi
            send_vk_file "$2" "${3:-Test VK file upload}"
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
