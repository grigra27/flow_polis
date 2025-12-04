#!/bin/bash

# Скрипт для деплоя исправлений commission_rate на продакшн
# Использование: ./deploy_commission_fix.sh

set -e  # Остановка при ошибке

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Деплой исправлений commission_rate на продакшн                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для вывода с цветом
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "ℹ $1"
}

# Проверка что мы на продакшн сервере
echo "Шаг 1: Проверка окружения"
echo "─────────────────────────────────────────────────────────────────"

if [ -f ".env.prod" ]; then
    print_success "Найден файл .env.prod"
else
    print_warning "Файл .env.prod не найден. Вы уверены что это продакшн?"
    read -p "Продолжить? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        print_error "Деплой отменен"
        exit 1
    fi
fi

# Проверка что виртуальное окружение активировано
if [ -z "$VIRTUAL_ENV" ]; then
    print_warning "Виртуальное окружение не активировано"
    if [ -d "venv" ]; then
        print_info "Активирую venv..."
        source venv/bin/activate
        print_success "venv активирован"
    else
        print_error "Директория venv не найдена"
        exit 1
    fi
else
    print_success "Виртуальное окружение активно: $VIRTUAL_ENV"
fi

echo ""

# Обновление кода
echo "Шаг 2: Обновление кода"
echo "─────────────────────────────────────────────────────────────────"

print_info "Получение последних изменений из git..."
git pull origin main

if [ $? -eq 0 ]; then
    print_success "Код обновлен"
else
    print_error "Ошибка при обновлении кода"
    exit 1
fi

echo ""

# Бэкап базы данных
echo "Шаг 3: Создание бэкапа базы данных"
echo "─────────────────────────────────────────────────────────────────"

BACKUP_DIR="backups"
mkdir -p $BACKUP_DIR

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Определяем тип базы данных из .env
if grep -q "DATABASE_URL.*postgres" .env* 2>/dev/null; then
    print_info "Обнаружена PostgreSQL база"

    # Извлекаем параметры подключения
    DB_NAME=$(grep "POSTGRES_DB" .env.prod | cut -d '=' -f2)
    DB_USER=$(grep "POSTGRES_USER" .env.prod | cut -d '=' -f2)

    BACKUP_FILE="$BACKUP_DIR/backup_commission_fix_${TIMESTAMP}.sql"

    print_info "Создание бэкапа: $BACKUP_FILE"
    pg_dump -U $DB_USER -d $DB_NAME > $BACKUP_FILE

    if [ $? -eq 0 ]; then
        print_success "Бэкап создан: $BACKUP_FILE"
    else
        print_error "Ошибка при создании бэкапа"
        exit 1
    fi

elif [ -f "db.sqlite3" ]; then
    print_info "Обнаружена SQLite база"

    BACKUP_FILE="$BACKUP_DIR/db.sqlite3.backup_${TIMESTAMP}"

    print_info "Создание бэкапа: $BACKUP_FILE"
    cp db.sqlite3 $BACKUP_FILE

    if [ $? -eq 0 ]; then
        print_success "Бэкап создан: $BACKUP_FILE"
    else
        print_error "Ошибка при создании бэкапа"
        exit 1
    fi
else
    print_error "Не удалось определить тип базы данных"
    exit 1
fi

echo ""

# Перезапуск приложения
echo "Шаг 4: Перезапуск приложения"
echo "─────────────────────────────────────────────────────────────────"

# Определяем способ запуска
if systemctl is-active --quiet gunicorn; then
    print_info "Перезапуск через systemd..."
    sudo systemctl restart gunicorn
    print_success "Gunicorn перезапущен"

elif [ -f "docker-compose.yml" ] || [ -f "docker-compose.prod.yml" ]; then
    print_info "Перезапуск через docker-compose..."
    docker-compose restart web
    print_success "Docker контейнер перезапущен"

elif command -v supervisorctl &> /dev/null; then
    print_info "Перезапуск через supervisor..."
    sudo supervisorctl restart all
    print_success "Supervisor перезапущен"

else
    print_warning "Не удалось определить способ перезапуска"
    print_info "Перезапустите приложение вручную"
fi

echo ""

# Ожидание запуска приложения
print_info "Ожидание запуска приложения (5 секунд)..."
sleep 5

echo ""

# Исправление данных
echo "Шаг 5: Исправление данных в базе"
echo "─────────────────────────────────────────────────────────────────"

print_warning "Сейчас будет запущен скрипт исправления данных"
print_info "Скрипт найдет все платежи без commission_rate и исправит их"
echo ""

read -p "Продолжить? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    print_error "Исправление данных отменено"
    print_warning "Код обновлен, но данные не исправлены"
    exit 1
fi

echo ""
print_info "Запуск скрипта исправления..."
echo ""

# Запускаем скрипт с автоматическим подтверждением
echo "да" | python fix_all_missing_commission_rates.py

if [ $? -eq 0 ]; then
    print_success "Данные исправлены"
else
    print_error "Ошибка при исправлении данных"
    print_warning "Возможно потребуется откат базы из бэкапа: $BACKUP_FILE"
    exit 1
fi

echo ""

# Проверка результатов
echo "Шаг 6: Проверка результатов"
echo "─────────────────────────────────────────────────────────────────"

print_info "Запуск проверки..."
echo ""

python check_commission_rate_impact.py | grep -A 1 "Найдено платежей\|Все платежи"

if [ $? -eq 0 ]; then
    print_success "Проверка завершена"
else
    print_warning "Не удалось выполнить проверку"
fi

echo ""

# Итоги
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Деплой завершен успешно!                                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

print_success "Код обновлен"
print_success "Бэкап создан: $BACKUP_FILE"
print_success "Приложение перезапущено"
print_success "Данные исправлены"

echo ""
print_info "Следующие шаги:"
echo "  1. Проверьте отчет по КВ в веб-интерфейсе"
echo "  2. Создайте тестовый платеж для проверки"
echo "  3. Мониторьте логи приложения"
echo ""

print_warning "Бэкап базы сохранен на 7 дней: $BACKUP_FILE"
echo ""

# Показываем информацию об откате
echo "Для отката изменений:"
echo "  git checkout <previous-commit>"
echo "  sudo systemctl restart gunicorn"
echo "  # Восстановите базу из: $BACKUP_FILE"
echo ""
