#!/bin/bash

# Скрипт для проверки настройки GitHub Secrets
# Использование: ./scripts/verify-github-secrets.sh

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Конфигурация
DROPLET_HOST="64.227.75.233"
DROPLET_USER="root"
KEY_NAME="github_actions_deploy"
KEY_PATH="$HOME/.ssh/$KEY_NAME"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Проверка настройки GitHub Secrets                         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Счетчики
PASSED=0
FAILED=0
WARNINGS=0

# Функция для проверки
check() {
    local name="$1"
    local command="$2"
    local success_msg="$3"
    local error_msg="$4"
    
    echo -n "Проверка: $name... "
    
    if eval "$command" &>/dev/null; then
        echo -e "${GREEN}✅ PASS${NC}"
        [ -n "$success_msg" ] && echo "  ℹ️  $success_msg"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        [ -n "$error_msg" ] && echo "  ⚠️  $error_msg"
        ((FAILED++))
        return 1
    fi
}

# Функция для предупреждения
warn() {
    local name="$1"
    local message="$2"
    
    echo -e "${YELLOW}⚠️  WARNING: $name${NC}"
    echo "  $message"
    ((WARNINGS++))
}

echo -e "${BLUE}═══ Локальная проверка ═══${NC}\n"

# Проверка 1: Существование SSH ключа
check "SSH ключ существует" \
    "[ -f '$KEY_PATH' ]" \
    "Приватный ключ найден: $KEY_PATH" \
    "Ключ не найден. Запустите: ./scripts/setup-github-secrets.sh"

# Проверка 2: Существование публичного ключа
check "Публичный SSH ключ существует" \
    "[ -f '${KEY_PATH}.pub' ]" \
    "Публичный ключ найден: ${KEY_PATH}.pub" \
    "Публичный ключ не найден"

# Проверка 3: Права на приватный ключ
if [ -f "$KEY_PATH" ]; then
    PERMS=$(stat -f "%OLp" "$KEY_PATH" 2>/dev/null || stat -c "%a" "$KEY_PATH" 2>/dev/null)
    if [ "$PERMS" = "600" ]; then
        echo -e "Проверка: Права на приватный ключ... ${GREEN}✅ PASS${NC}"
        echo "  ℹ️  Права корректны: 600"
        ((PASSED++))
    else
        echo -e "Проверка: Права на приватный ключ... ${YELLOW}⚠️  WARNING${NC}"
        echo "  ⚠️  Права: $PERMS (рекомендуется: 600)"
        echo "  Исправить: chmod 600 $KEY_PATH"
        ((WARNINGS++))
    fi
fi

echo ""
echo -e "${BLUE}═══ Проверка подключения к Droplet ═══${NC}\n"

# Проверка 4: Доступность Droplet
check "Droplet доступен" \
    "ping -c 1 -W 2 $DROPLET_HOST" \
    "Droplet отвечает на ping" \
    "Droplet недоступен. Проверьте IP адрес и сетевое подключение"

# Проверка 5: SSH подключение (любым доступным способом)
check "SSH подключение работает" \
    "ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no $DROPLET_USER@$DROPLET_HOST 'echo ok'" \
    "SSH подключение успешно" \
    "SSH подключение не работает. Проверьте SSH ключи и доступ"

# Проверка 6: SSH подключение с GitHub Actions ключом
if [ -f "$KEY_PATH" ]; then
    check "SSH с GitHub Actions ключом" \
        "ssh -i '$KEY_PATH' -o ConnectTimeout=5 -o StrictHostKeyChecking=no $DROPLET_USER@$DROPLET_HOST 'echo ok'" \
        "Ключ работает корректно" \
        "Ключ не работает. Убедитесь, что публичный ключ добавлен на сервер"
fi

# Проверка 7: Публичный ключ на сервере
if [ -f "${KEY_PATH}.pub" ]; then
    PUBLIC_KEY_FINGERPRINT=$(ssh-keygen -lf "${KEY_PATH}.pub" | awk '{print $2}')
    if ssh -o ConnectTimeout=5 "$DROPLET_USER@$DROPLET_HOST" "grep -q '$(cat ${KEY_PATH}.pub)' ~/.ssh/authorized_keys" 2>/dev/null; then
        echo -e "Проверка: Публичный ключ на сервере... ${GREEN}✅ PASS${NC}"
        echo "  ℹ️  Ключ найден в authorized_keys"
        ((PASSED++))
    else
        echo -e "Проверка: Публичный ключ на сервере... ${RED}❌ FAIL${NC}"
        echo "  ⚠️  Ключ не найден в authorized_keys"
        echo "  Добавить: cat ${KEY_PATH}.pub | ssh $DROPLET_USER@$DROPLET_HOST 'cat >> ~/.ssh/authorized_keys'"
        ((FAILED++))
    fi
fi

echo ""
echo -e "${BLUE}═══ Проверка Docker окружения на Droplet ═══${NC}\n"

# Проверка 8: Docker установлен
check "Docker установлен на Droplet" \
    "ssh -o ConnectTimeout=5 $DROPLET_USER@$DROPLET_HOST 'docker --version'" \
    "Docker найден" \
    "Docker не установлен. Запустите: ./scripts/setup-droplet.sh"

# Проверка 9: Docker Compose установлен
check "Docker Compose установлен" \
    "ssh -o ConnectTimeout=5 $DROPLET_USER@$DROPLET_HOST 'docker compose version'" \
    "Docker Compose найден" \
    "Docker Compose не установлен"

# Проверка 10: Директория приложения существует
check "Директория приложения существует" \
    "ssh -o ConnectTimeout=5 $DROPLET_USER@$DROPLET_HOST '[ -d ~/insurance_broker ] || [ -d /opt/insurance_broker ]'" \
    "Директория найдена" \
    "Директория не найдена. Возможно, деплой еще не выполнялся"

echo ""
echo -e "${BLUE}═══ Проверка GitHub ═══${NC}\n"

# Проверка 11: Git репозиторий
if git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "Проверка: Git репозиторий... ${GREEN}✅ PASS${NC}"
    echo "  ℹ️  Находимся в Git репозитории"
    ((PASSED++))
else
    echo -e "Проверка: Git репозиторий... ${RED}❌ FAIL${NC}"
    echo "  ⚠️  Не Git репозиторий"
    ((FAILED++))
fi

# Проверка 12: GitHub remote
if git remote get-url origin &>/dev/null; then
    REMOTE_URL=$(git remote get-url origin)
    echo -e "Проверка: GitHub remote... ${GREEN}✅ PASS${NC}"
    echo "  ℹ️  Remote: $REMOTE_URL"
    ((PASSED++))
else
    echo -e "Проверка: GitHub remote... ${RED}❌ FAIL${NC}"
    echo "  ⚠️  GitHub remote не настроен"
    ((FAILED++))
fi

# Проверка 13: GitHub Actions workflow
if [ -f ".github/workflows/deploy.yml" ]; then
    echo -e "Проверка: GitHub Actions workflow... ${GREEN}✅ PASS${NC}"
    echo "  ℹ️  Workflow файл найден"
    ((PASSED++))
else
    echo -e "Проверка: GitHub Actions workflow... ${RED}❌ FAIL${NC}"
    echo "  ⚠️  Workflow файл не найден: .github/workflows/deploy.yml"
    ((FAILED++))
fi

echo ""
echo -e "${BLUE}═══ Проверка конфигурационных файлов ═══${NC}\n"

# Проверка 14: docker-compose.prod.yml
check "docker-compose.prod.yml существует" \
    "[ -f 'docker-compose.prod.yml' ]" \
    "Файл найден" \
    "Файл не найден"

# Проверка 15: Dockerfile
check "Dockerfile существует" \
    "[ -f 'Dockerfile' ]" \
    "Файл найден" \
    "Файл не найден"

# Проверка 16: Nginx конфигурация
check "Nginx конфигурация существует" \
    "[ -f 'nginx/default.conf' ]" \
    "Файл найден" \
    "Файл не найден"

# Проверка 17: entrypoint.sh
check "entrypoint.sh существует" \
    "[ -f 'entrypoint.sh' ]" \
    "Файл найден" \
    "Файл не найден"

# Проверка 18: requirements.prod.txt
check "requirements.prod.txt существует" \
    "[ -f 'requirements.prod.txt' ]" \
    "Файл найден" \
    "Файл не найден"

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Результаты проверки                                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

TOTAL=$((PASSED + FAILED))
echo -e "${GREEN}✅ Пройдено: $PASSED${NC}"
echo -e "${RED}❌ Провалено: $FAILED${NC}"
echo -e "${YELLOW}⚠️  Предупреждений: $WARNINGS${NC}"
echo -e "Всего проверок: $TOTAL"
echo ""

# Итоговый статус
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!                                 ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Система готова к деплою через GitHub Actions!"
    echo ""
    echo "Следующие шаги:"
    echo "1. Убедитесь, что добавили секреты в GitHub:"
    echo "   - SSH_PRIVATE_KEY"
    echo "   - DROPLET_HOST"
    echo "   - DROPLET_USER"
    echo ""
    echo "2. Проверьте секреты:"
    echo "   GitHub → Settings → Secrets and variables → Actions"
    echo ""
    echo "3. Сделайте тестовый деплой:"
    echo "   git commit --allow-empty -m 'test: verify deployment'"
    echo "   git push origin main"
    echo ""
    exit 0
else
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ❌ ОБНАРУЖЕНЫ ПРОБЛЕМЫ                                    ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Исправьте ошибки выше перед деплоем."
    echo ""
    echo "Полезные команды:"
    echo "  - Настроить SSH ключ: ./scripts/setup-github-secrets.sh"
    echo "  - Настроить Droplet: ./scripts/setup-droplet.sh"
    echo "  - Документация: docs/GITHUB_SECRETS_SETUP.md"
    echo ""
    exit 1
fi
