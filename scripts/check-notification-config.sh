#!/bin/bash
# check-notification-config.sh
#
# Проверяет что все переменные для Telegram/VK нотификаций присутствуют
# в .env.prod и что Django-контейнер видит те же значения.
#
# Запускать с корня проекта: ./scripts/check-notification-config.sh
# Или из любого места:       /path/to/scripts/check-notification-config.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$APP_DIR/.env.prod"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅${NC} $*"; }
fail() { echo -e "${RED}❌${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️ ${NC} $*"; }

ERRORS=0

echo ""
echo "=== Notification config sanity check ==="
echo ""

# ── 1. Проверка .env.prod ────────────────────────────────────────────────────

if [ ! -f "$ENV_FILE" ]; then
    fail ".env.prod не найден: $ENV_FILE"
    exit 1
fi
ok ".env.prod найден"

# Загружаем переменные без экспорта в shell (чтобы не засорять окружение)
_get_env() {
    grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

declare -A REQUIRED_VARS=(
    [TELEGRAM_BOT_TOKEN]="digits:alphanumeric, напр. 123456:ABCdef"
    [TELEGRAM_CHAT_ID]="числовой ID чата, напр. -1001234567890"
    [VK_COMMUNITY_TOKEN]="токен VK community"
    [VK_USER_ID]="числовой ID пользователя VK"
)

echo ""
echo "--- Переменные в .env.prod ---"
echo ""

for var in "${!REQUIRED_VARS[@]}"; do
    value="$(_get_env "$var")"
    hint="${REQUIRED_VARS[$var]}"
    if [ -z "$value" ]; then
        fail "$var  ← отсутствует или пуст  ($hint)"
        ERRORS=$((ERRORS + 1))
    else
        masked="${value:0:6}***${value: -4}"
        ok "$var = $masked"
    fi
done

# Базовая проверка формата TELEGRAM_BOT_TOKEN
TG_TOKEN="$(_get_env TELEGRAM_BOT_TOKEN)"
if [ -n "$TG_TOKEN" ] && ! echo "$TG_TOKEN" | grep -qE '^[0-9]+:[A-Za-z0-9_-]+$'; then
    warn "TELEGRAM_BOT_TOKEN имеет неожиданный формат (ожидается digits:alphanumeric)"
fi

# ── 2. Сверка с Django-контейнером (если запущен) ───────────────────────────

echo ""
echo "--- Django-контейнер ---"
echo ""

COMPOSE_FILE="$APP_DIR/docker-compose.prod.yml"

if ! command -v docker-compose &>/dev/null && ! command -v docker &>/dev/null; then
    warn "docker не найден — пропускаем проверку контейнера"
elif ! docker-compose -f "$COMPOSE_FILE" ps 2>/dev/null | grep -q "insurance_broker_web.*Up"; then
    warn "web-контейнер не запущен — пропускаем сверку с Django"
else
    PYTHON_CHECK=$(docker-compose -f "$COMPOSE_FILE" exec -T web python - <<'PYEOF'
import os
keys = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "VK_COMMUNITY_TOKEN", "VK_USER_ID"]
for k in keys:
    v = os.environ.get(k, "")
    if v:
        masked = v[:6] + "***" + v[-4:]
        print(f"OK {k}={masked}")
    else:
        print(f"MISSING {k}")
PYEOF
    )

    ENV_MISMATCH=0
    while IFS= read -r line; do
        status="${line%% *}"
        rest="${line#* }"
        var="${rest%%=*}"
        django_masked="${rest#*=}"
        env_val="$(_get_env "$var")"
        env_masked="${env_val:0:6}***${env_val: -4}"

        if [ "$status" = "MISSING" ]; then
            fail "Django не видит $var"
            ERRORS=$((ERRORS + 1))
        elif [ "$django_masked" != "$env_masked" ]; then
            fail "$var расходится: .env.prod=$env_masked  Django=$django_masked"
            ENV_MISMATCH=$((ENV_MISMATCH + 1))
            ERRORS=$((ERRORS + 1))
        else
            ok "$var совпадает ($django_masked)"
        fi
    done <<< "$PYTHON_CHECK"

    if [ "$ENV_MISMATCH" -gt 0 ]; then
        echo ""
        warn "Расхождение означает что .env.prod изменили но не перезапустили контейнеры."
        warn "Исправление: set -a; source .env.prod; set +a && docker-compose -f docker-compose.prod.yml up -d"
    fi
fi

# ── Итог ─────────────────────────────────────────────────────────────────────

echo ""
if [ "$ERRORS" -eq 0 ]; then
    ok "Все проверки пройдены — конфигурация нотификаций консистентна."
else
    fail "Найдено проблем: $ERRORS. Исправь и запусти скрипт снова."
    exit 1
fi
echo ""
