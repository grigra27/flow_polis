#!/bin/bash

# ============================================================
# ⚠️  DEPRECATED — см. PLAN.md, пункт 11.1
# ============================================================
# Этот скрипт настраивает cron для monitor-logs-telegram.sh, который
# теперь deprecated (дублирует Python TelegramHandler в Django).
# Не запускай этот setup на новых серверах.
# Подробности — в шапке monitor-logs-telegram.sh.
# ============================================================

# setup-error-monitoring.sh
# Скрипт для быстрой настройки мониторинга ошибок через Telegram

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[SETUP]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[SETUP]${NC} $1"
}

log_error() {
    echo -e "${RED}[SETUP]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🚨 Настройка мониторинга ошибок через Telegram"
echo "=============================================="
echo ""

# Step 1: Check if Telegram is already configured
log_step "1. Проверка настроек Telegram..."

source "$SCRIPT_DIR/telegram-config.sh"

if [ "$TELEGRAM_ENABLED" = "true" ] && [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    log_info "✅ Telegram уже настроен для бэкапов"
    log_info "   Bot Token: ${TELEGRAM_BOT_TOKEN:0:10}..."
    log_info "   Chat ID: $TELEGRAM_CHAT_ID"
else
    log_error "❌ Telegram не настроен!"
    log_error "   Сначала настройте Telegram для бэкапов:"
    log_error "   ./scripts/setup-telegram.sh"
    log_error "   Или следуйте инструкциям в TELEGRAM_SETUP_GUIDE.md"
    exit 1
fi

# Step 2: Check Python dependencies
log_step "2. Проверка зависимостей Python..."

# Check if psutil is available in Docker container
if docker-compose -f docker-compose.prod.yml exec web python -c "import psutil" 2>/dev/null; then
    log_info "✅ psutil доступен в контейнере"
else
    log_error "❌ psutil не найден в контейнере!"
    log_error "   Убедитесь что requirements.txt содержит psutil>=5.9.0"
    log_error "   И пересоберите Docker контейнер:"
    log_error "   docker-compose -f docker-compose.prod.yml build web"
    exit 1
fi

# Step 3: Test Django error monitoring
log_step "3. Тестирование Django мониторинга ошибок..."

cd "$PROJECT_DIR"

if docker-compose -f docker-compose.prod.yml exec web python manage.py test_telegram_errors --test-custom; then
    log_info "✅ Django мониторинг ошибок работает"
else
    log_error "❌ Ошибка в Django мониторинге"
    exit 1
fi

# Step 4: Test system health check
log_step "4. Тестирование проверки системы..."

if docker-compose -f docker-compose.prod.yml exec web python manage.py system_health_check --check-all --notify-telegram; then
    log_info "✅ Проверка системы работает"
else
    log_warn "⚠️ Проблемы с проверкой системы (не критично)"
fi

# Step 5: Test log monitoring
log_step "5. Тестирование мониторинга логов..."

if "$SCRIPT_DIR/monitor-logs-telegram.sh" --test; then
    log_info "✅ Мониторинг логов работает"
else
    log_warn "⚠️ Проблемы с мониторингом логов (не критично)"
fi

# Step 6: Setup systemd service (optional)
log_step "6. Настройка systemd service для мониторинга логов..."

read -p "Хотите настроить автоматический мониторинг логов через systemd? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Создание systemd service..."

    sudo tee /etc/systemd/system/telegram-log-monitor.service > /dev/null <<EOF
[Unit]
Description=Telegram Log Monitor for Insurance Broker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$SCRIPT_DIR/monitor-logs-telegram.sh --daemon
Restart=always
RestartSec=10
Environment=PATH=/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable telegram-log-monitor
    sudo systemctl start telegram-log-monitor

    log_info "✅ Systemd service создан и запущен"
    log_info "   Статус: sudo systemctl status telegram-log-monitor"
    log_info "   Логи: sudo journalctl -u telegram-log-monitor -f"
else
    log_info "Пропускаем настройку systemd service"
fi

# Step 7: Setup cron jobs (optional)
log_step "7. Настройка cron задач для проверки системы..."

read -p "Хотите добавить регулярную проверку системы в cron? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Добавление cron задач..."

    # Create temporary cron file
    TEMP_CRON=$(mktemp)

    # Get existing crontab
    crontab -l 2>/dev/null > "$TEMP_CRON" || true

    # Add health check job if not exists
    if ! grep -q "system_health_check" "$TEMP_CRON"; then
        echo "# Insurance Broker - System Health Check (every 30 minutes)" >> "$TEMP_CRON"
        echo "*/30 * * * * cd $PROJECT_DIR && docker-compose -f docker-compose.prod.yml exec -T web python manage.py system_health_check --check-all --notify-telegram >> $PROJECT_DIR/logs/health-check.log 2>&1" >> "$TEMP_CRON"
        echo "" >> "$TEMP_CRON"
    fi

    # Add daily digest job if not exists
    if ! grep -q "daily_digest" "$TEMP_CRON"; then
        echo "# Insurance Broker - Daily Digest (every day at 6:00 AM MSK)" >> "$TEMP_CRON"
        echo "0 3 * * * cd $PROJECT_DIR && docker-compose -f docker-compose.prod.yml exec -T web python manage.py daily_digest >> $PROJECT_DIR/logs/daily-digest.log 2>&1" >> "$TEMP_CRON"
        echo "" >> "$TEMP_CRON"
    fi

    # Install new crontab
    crontab "$TEMP_CRON"
    rm "$TEMP_CRON"

    log_info "✅ Cron задачи добавлены"
    log_info "   Проверка системы каждые 30 минут"
    log_info "   Ежедневный дайджест в 6:00 МСК"
else
    log_info "Пропускаем настройку cron задач"
fi

# Step 8: Configure rate limiting
log_step "8. Настройка rate limiting..."

ENV_FILE="$PROJECT_DIR/.env.prod"
if [ -f "$ENV_FILE" ]; then
    if ! grep -q "TELEGRAM_ERROR_RATE_LIMIT" "$ENV_FILE"; then
        echo "" >> "$ENV_FILE"
        echo "# Telegram Error Monitoring" >> "$ENV_FILE"
        echo "TELEGRAM_ERROR_RATE_LIMIT=10" >> "$ENV_FILE"
        log_info "✅ Добавлен TELEGRAM_ERROR_RATE_LIMIT в .env.prod"
    else
        log_info "✅ TELEGRAM_ERROR_RATE_LIMIT уже настроен"
    fi
else
    log_warn "⚠️ .env.prod не найден, добавьте вручную:"
    log_warn "   TELEGRAM_ERROR_RATE_LIMIT=10"
fi

# Final summary
echo ""
echo "🎉 Настройка завершена!"
echo "======================"
echo ""
log_info "✅ Что настроено:"
echo "   • Django logging handler для автоматических уведомлений об ошибках"
echo "   • Команды для тестирования и мониторинга системы"
echo "   • Мониторинг файлов логов в реальном времени"
echo "   • Rate limiting для предотвращения спама"
echo "   • Ежедневный дайджест в 6:00 МСК"
echo ""

log_info "📋 Полезные команды:"
echo "   # Тестирование"
echo "   docker-compose -f docker-compose.prod.yml exec web python manage.py test_telegram_errors --test-error"
echo "   docker-compose -f docker-compose.prod.yml exec web python manage.py system_health_check --check-all --notify-telegram"
echo "   docker-compose -f docker-compose.prod.yml exec web python manage.py daily_digest --test"
echo "   ./scripts/monitor-logs-telegram.sh --status"
echo ""
echo "   # Мониторинг"
echo "   ./scripts/monitor-logs-telegram.sh --daemon"
echo "   sudo systemctl status telegram-log-monitor"
echo ""

log_info "📖 Документация:"
echo "   • TELEGRAM_ERROR_MONITORING.md - полное руководство"
echo "   • TELEGRAM_SETUP_GUIDE.md - настройка Telegram бота"
echo ""

log_info "🔔 Теперь все критические ошибки будут отправляться в тот же Telegram канал что и бэкапы!"

exit 0
