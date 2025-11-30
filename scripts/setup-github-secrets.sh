#!/bin/bash

# Скрипт для настройки SSH ключа для GitHub Actions
# Использование: ./scripts/setup-github-secrets.sh

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
echo -e "${BLUE}║  Настройка SSH ключа для GitHub Actions                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Функция для вывода шагов
print_step() {
    echo -e "\n${BLUE}▶ $1${NC}"
}

# Функция для вывода успеха
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# Функция для вывода ошибки
print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Функция для вывода предупреждения
print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Шаг 1: Проверка существующего ключа
print_step "Шаг 1: Проверка существующего SSH ключа"

if [ -f "$KEY_PATH" ]; then
    print_warning "SSH ключ уже существует: $KEY_PATH"
    read -p "Хотите создать новый ключ? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Используем существующий ключ"
    else
        print_warning "Создаем резервную копию старого ключа"
        mv "$KEY_PATH" "${KEY_PATH}.backup.$(date +%Y%m%d_%H%M%S)"
        mv "${KEY_PATH}.pub" "${KEY_PATH}.pub.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true

        print_step "Создание нового SSH ключа"
        ssh-keygen -t ed25519 -C "github-actions-deploy" -f "$KEY_PATH" -N ""
        print_success "Новый SSH ключ создан"
    fi
else
    print_step "Создание SSH ключа"
    ssh-keygen -t ed25519 -C "github-actions-deploy" -f "$KEY_PATH" -N ""
    print_success "SSH ключ создан: $KEY_PATH"
fi

# Шаг 2: Проверка подключения к Droplet
print_step "Шаг 2: Проверка подключения к Droplet"

if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$DROPLET_USER@$DROPLET_HOST" "echo 'connected'" &>/dev/null; then
    print_success "Подключение к Droplet успешно"
else
    print_error "Не удалось подключиться к Droplet"
    print_warning "Убедитесь, что:"
    echo "  1. Droplet запущен и доступен"
    echo "  2. У вас есть SSH доступ к серверу"
    echo "  3. IP адрес правильный: $DROPLET_HOST"
    exit 1
fi

# Шаг 3: Добавление публичного ключа на Droplet
print_step "Шаг 3: Добавление публичного ключа на Droplet"

PUBLIC_KEY=$(cat "${KEY_PATH}.pub")

# Проверяем, не добавлен ли уже этот ключ
if ssh "$DROPLET_USER@$DROPLET_HOST" "grep -q '$PUBLIC_KEY' ~/.ssh/authorized_keys" 2>/dev/null; then
    print_warning "Публичный ключ уже добавлен на сервер"
else
    # Добавляем ключ на сервер
    cat "${KEY_PATH}.pub" | ssh "$DROPLET_USER@$DROPLET_HOST" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    print_success "Публичный ключ добавлен на Droplet"
fi

# Шаг 4: Проверка SSH подключения с новым ключом
print_step "Шаг 4: Проверка SSH подключения с новым ключом"

if ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no "$DROPLET_USER@$DROPLET_HOST" "echo 'SSH key works!'" &>/dev/null; then
    print_success "SSH подключение с новым ключом работает!"
else
    print_error "SSH подключение с новым ключом не работает"
    exit 1
fi

# Шаг 5: Вывод информации для GitHub Secrets
print_step "Шаг 5: Информация для GitHub Secrets"

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Добавьте следующие секреты в GitHub                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Перейдите: Settings → Secrets and variables → Actions → New repository secret${NC}"
echo ""

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Секрет 1: SSH_PRIVATE_KEY${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Name: SSH_PRIVATE_KEY"
echo ""
echo "Value (скопируйте всё ниже, включая BEGIN и END):"
echo ""
cat "$KEY_PATH"
echo ""

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Секрет 2: DROPLET_HOST${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Name: DROPLET_HOST"
echo "Value: $DROPLET_HOST"
echo ""

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Секрет 3: DROPLET_USER${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Name: DROPLET_USER"
echo "Value: $DROPLET_USER"
echo ""

# Шаг 6: Сохранение информации в файл
print_step "Шаг 6: Сохранение информации"

INFO_FILE="github_secrets_info.txt"
cat > "$INFO_FILE" << EOF
GitHub Secrets Configuration
Generated: $(date)

=== Секрет 1: SSH_PRIVATE_KEY ===
Name: SSH_PRIVATE_KEY
Value:
$(cat "$KEY_PATH")

=== Секрет 2: DROPLET_HOST ===
Name: DROPLET_HOST
Value: $DROPLET_HOST

=== Секрет 3: DROPLET_USER ===
Name: DROPLET_USER
Value: $DROPLET_USER

=== Инструкции ===
1. Перейдите в ваш GitHub репозиторий
2. Settings → Secrets and variables → Actions
3. Нажмите "New repository secret"
4. Добавьте каждый из трех секретов выше

=== Проверка ===
После добавления секретов:
1. Сделайте коммит: git commit --allow-empty -m "test: verify secrets"
2. Отправьте в main: git push origin main
3. Проверьте Actions: GitHub → Actions → Deploy to Production

=== Безопасность ===
ВАЖНО: Удалите этот файл после добавления секретов в GitHub!
Команда: rm $INFO_FILE
EOF

print_success "Информация сохранена в файл: $INFO_FILE"
print_warning "ВАЖНО: Удалите этот файл после добавления секретов в GitHub!"
echo "  Команда: rm $INFO_FILE"

# Шаг 7: Финальные инструкции
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Следующие шаги                                            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "1. Добавьте три секрета в GitHub (см. выше)"
echo "2. Проверьте настройку:"
echo "   git commit --allow-empty -m 'test: verify GitHub Actions'"
echo "   git push origin main"
echo "3. Проверьте статус деплоя:"
echo "   GitHub → Actions → Deploy to Production"
echo "4. Удалите файл с секретами:"
echo "   rm $INFO_FILE"
echo ""

print_success "Настройка завершена!"
echo ""
echo -e "${YELLOW}Полная документация: docs/GITHUB_SECRETS_SETUP.md${NC}"
echo -e "${YELLOW}Краткая справка: GITHUB_SECRETS_QUICK_REFERENCE.md${NC}"
