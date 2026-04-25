#!/bin/bash

# ============================================================
# ⚠️  DEPRECATED — см. PLAN.md, пункт 11.1
# ============================================================
# Этот скрипт дублирует функциональность Python TelegramHandler
# (apps/core/telegram_handler.py), который уже подключён в LOGGING
# config Django (config/settings.py). Любой logger.error()/critical()
# из Django-кода — включая security CRITICAL события (брутфорс) —
# уже отправляется в Telegram через Python.
#
# Этот bash-скрипт раньше был fallback'ом на случай если Django упадёт.
# В результате на проде получаются ДВА сообщения за каждую ошибку:
#   • «🚨 Critical Error Detected» от Python (через несколько секунд)
#   • «🚨 Log Error Detected»     от bash    (через ~60 секунд)
#
# Перед окончательным удалением:
# 1) Убедись, что Python-канал работает:
#    docker compose -f docker-compose.prod.yml exec web \
#      python manage.py test_telegram_errors --test-security
#    Должно прийти «🚨 Critical Error Detected» за ~5 секунд.
# 2) Отключи cron/daemon на сервере:
#    crontab -l | grep monitor-logs-telegram     # найди запись
#    crontab -e                                  # закомментируй её
#    pgrep -af monitor-logs-telegram             # проверь нет ли daemon
# 3) После недели наблюдения этот файл и setup-error-monitoring.sh
#    можно удалить из репо.
# ============================================================
#
# monitor-logs-telegram.sh
# Мониторинг логов Django на предмет критических ошибок с уведомлениями в Telegram
# Может работать как демон или как разовая проверка

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Get script directory and load Telegram functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/telegram-notify.sh"

# Configuration
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/../logs}"
DJANGO_LOG="${DJANGO_LOG:-$LOG_DIR/django.log}"
SECURITY_LOG="${SECURITY_LOG:-$LOG_DIR/security.log}"
STATE_FILE="${STATE_FILE:-$LOG_DIR/.monitor_state}"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"  # seconds
MAX_ERRORS_PER_HOUR="${MAX_ERRORS_PER_HOUR:-10}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[MONITOR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[MONITOR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[MONITOR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Initialize state file
init_state_file() {
    if [ ! -f "$STATE_FILE" ]; then
        echo "django_log_position=0" > "$STATE_FILE"
        echo "security_log_position=0" >> "$STATE_FILE"
        echo "last_error_count=0" >> "$STATE_FILE"
        echo "last_error_time=0" >> "$STATE_FILE"
        log_info "Initialized state file: $STATE_FILE"
    fi
}

# Read state from file
read_state() {
    if [ -f "$STATE_FILE" ]; then
        source "$STATE_FILE"
    fi

    # Initialize variables if not set
    django_log_position=${django_log_position:-0}
    security_log_position=${security_log_position:-0}
    last_error_count=${last_error_count:-0}
    last_error_time=${last_error_time:-0}
}

# Write state to file
write_state() {
    echo "django_log_position=$django_log_position" > "$STATE_FILE"
    echo "security_log_position=$security_log_position" >> "$STATE_FILE"
    echo "last_error_count=$last_error_count" >> "$STATE_FILE"
    echo "last_error_time=$last_error_time" >> "$STATE_FILE"
}

# Check if we should send notification (rate limiting)
should_notify() {
    local current_time=$(date +%s)
    local hour_ago=$((current_time - 3600))

    # Initialize variables if empty
    last_error_time=${last_error_time:-0}
    last_error_count=${last_error_count:-0}

    # Reset counter if more than an hour passed
    if [ "$last_error_time" -lt "$hour_ago" ]; then
        last_error_count=0
    fi

    # Check if we're under the limit
    if [ "$last_error_count" -lt "$MAX_ERRORS_PER_HOUR" ]; then
        last_error_count=$((last_error_count + 1))
        last_error_time=$current_time
        return 0
    else
        return 1
    fi
}

# Send error notification to Telegram
send_error_notification() {
    local log_file="$1"
    local error_line="$2"
    local error_level="$3"

    if ! should_notify; then
        log_warn "Rate limit reached, skipping notification"
        return 0
    fi

    local timestamp=$(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')
    local log_name=$(basename "$log_file")

    # Extract relevant parts from log line
    local log_timestamp=$(echo "$error_line" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' | head -1)
    local error_message=$(echo "$error_line" | sed 's/^[^]]*] *//' | cut -c1-300)

    local message="🚨 Log Error Detected

📁 Log File: $log_name
📊 Level: $error_level
🕐 Detected: $timestamp
📝 Log Time: ${log_timestamp:-Unknown}
🖥 Server: $(hostname)

❗ Error Message:
$error_message

📋 Rate Limit: $last_error_count/$MAX_ERRORS_PER_HOUR per hour"

    send_telegram_message "$message" || true
}

# Monitor a single log file for new errors
monitor_log_file() {
    local log_file="$1"
    local position_var="$2"
    local current_position=${!position_var}

    if [ ! -f "$log_file" ]; then
        log_warn "Log file not found: $log_file"
        return 0
    fi

    # Get current file size
    local file_size=$(stat -c%s "$log_file" 2>/dev/null || stat -f%z "$log_file" 2>/dev/null || echo "0")

    # If file was rotated (size smaller than position), start from beginning
    if [ "$file_size" -lt "$current_position" ]; then
        log_info "Log file rotated, starting from beginning: $(basename "$log_file")"
        current_position=0
    fi

    # Read new lines since last check
    if [ "$file_size" -gt "$current_position" ]; then
        local new_lines=$(tail -c +$((current_position + 1)) "$log_file")
        local errors_found=0

        # Check for ERROR and CRITICAL level messages
        while IFS= read -r line; do
            if [[ "$line" =~ (ERROR|CRITICAL) ]]; then
                local error_level="ERROR"
                if [[ "$line" =~ CRITICAL ]]; then
                    error_level="CRITICAL"
                fi

                log_warn "Found $error_level in $(basename "$log_file"): ${line:0:100}..."
                send_error_notification "$log_file" "$line" "$error_level"
                errors_found=$((errors_found + 1))
            fi
        done <<< "$new_lines"

        if [ "$errors_found" -gt 0 ]; then
            log_info "Found $errors_found error(s) in $(basename "$log_file")"
        fi

        # Update position
        eval "$position_var=$file_size"
    fi
}

# Monitor all configured log files
monitor_logs() {
    read_state

    log_info "Monitoring logs for errors..."
    log_info "Django log: $DJANGO_LOG"
    log_info "Security log: $SECURITY_LOG"

    # Monitor Django log
    monitor_log_file "$DJANGO_LOG" "django_log_position"

    # Monitor Security log
    monitor_log_file "$SECURITY_LOG" "security_log_position"

    write_state
}

# Run as daemon
run_daemon() {
    log_info "Starting log monitor daemon (interval: ${CHECK_INTERVAL}s)"
    log_info "Press Ctrl+C to stop"

    # Send startup notification
    if check_telegram_enabled; then
        local message="🔍 Log Monitor Started

🕐 Time: $(TZ='Europe/Moscow' date '+%Y-%m-%d %H:%M:%S MSK')
⏱ Check Interval: ${CHECK_INTERVAL}s
📊 Rate Limit: $MAX_ERRORS_PER_HOUR errors/hour
🖥 Server: $(hostname)

Monitoring logs for ERROR and CRITICAL messages..."

        send_telegram_message "$message" || true
    fi

    # Main monitoring loop
    while true; do
        monitor_logs
        sleep "$CHECK_INTERVAL"
    done
}

# Test log monitoring
test_monitoring() {
    log_info "Testing log monitoring..."

    # Create test log entry
    local test_log="$LOG_DIR/test_monitor.log"
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR test_module Test error message for monitoring" >> "$test_log"

    # Monitor the test log
    local test_position=0
    monitor_log_file "$test_log" "test_position"

    # Clean up
    rm -f "$test_log"

    log_info "Test completed"
}

# Display usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Log monitoring script with Telegram notifications"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -d, --daemon            Run as daemon (continuous monitoring)"
    echo "  -o, --once              Run once and exit"
    echo "  -t, --test              Test monitoring functionality"
    echo "  -s, --status            Show current monitoring status"
    echo "  --test-telegram         Test Telegram connection"
    echo ""
    echo "Environment Variables:"
    echo "  LOG_DIR                 Log directory (default: ../logs)"
    echo "  CHECK_INTERVAL          Check interval in seconds (default: 60)"
    echo "  MAX_ERRORS_PER_HOUR     Max notifications per hour (default: 10)"
    echo ""
    echo "Examples:"
    echo "  $0 --daemon             Start continuous monitoring"
    echo "  $0 --once               Check logs once"
    echo "  $0 --test               Test monitoring functionality"
    echo ""
}

# Show monitoring status
show_status() {
    log_info "Log Monitor Status"
    echo ""

    read_state

    echo "Configuration:"
    echo "  Log Directory: $LOG_DIR"
    echo "  Django Log: $DJANGO_LOG"
    echo "  Security Log: $SECURITY_LOG"
    echo "  State File: $STATE_FILE"
    echo "  Check Interval: ${CHECK_INTERVAL}s"
    echo "  Max Errors/Hour: $MAX_ERRORS_PER_HOUR"
    echo ""

    echo "Current State:"
    echo "  Django Log Position: $django_log_position"
    echo "  Security Log Position: $security_log_position"
    echo "  Errors This Hour: $last_error_count"
    echo "  Last Error Time: $(date -d @$last_error_time 2>/dev/null || date -r $last_error_time 2>/dev/null || echo 'Never')"
    echo ""

    echo "Log Files:"
    if [ -f "$DJANGO_LOG" ]; then
        local size=$(stat -c%s "$DJANGO_LOG" 2>/dev/null || stat -f%z "$DJANGO_LOG" 2>/dev/null || echo "0")
        echo "  Django Log: EXISTS (${size} bytes)"
    else
        echo "  Django Log: NOT FOUND"
    fi

    if [ -f "$SECURITY_LOG" ]; then
        local size=$(stat -c%s "$SECURITY_LOG" 2>/dev/null || stat -f%z "$SECURITY_LOG" 2>/dev/null || echo "0")
        echo "  Security Log: EXISTS (${size} bytes)"
    else
        echo "  Security Log: NOT FOUND"
    fi

    echo ""
    echo "Telegram Status:"
    if check_telegram_enabled; then
        echo "  Status: ENABLED"
        echo "  Bot Token: ${TELEGRAM_BOT_TOKEN:0:10}..."
        echo "  Chat ID: $TELEGRAM_CHAT_ID"
    else
        echo "  Status: DISABLED"
    fi
}

# Main function
main() {
    # Create log directory if it doesn't exist
    mkdir -p "$LOG_DIR"

    # Initialize state file
    init_state_file

    # Parse command line arguments
    case "${1:-}" in
        -h|--help)
            usage
            exit 0
            ;;
        -d|--daemon)
            run_daemon
            ;;
        -o|--once)
            monitor_logs
            exit 0
            ;;
        -t|--test)
            test_monitoring
            exit 0
            ;;
        -s|--status)
            show_status
            exit 0
            ;;
        --test-telegram)
            test_telegram_connection
            exit $?
            ;;
        "")
            # No arguments - show usage
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

# Handle Ctrl+C gracefully
trap 'log_info "Stopping log monitor..."; exit 0' INT TERM

# Run main function
main "$@"
