#!/bin/bash

# Скрипт для настройки production credentials
# Запускать на сервере: ssh root@onbr.site
# cd ~/insurance_broker && bash scripts/setup-production-credentials.sh

set -e

echo "🔐 Настройка Production Credentials"
echo "===================================="
echo ""

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Проверка, что мы в правильной директории
if [ ! -f "docker-compose.prod.yml" ]; then
    echo -e "${RED}❌ Ошибка: docker-compose.prod.yml не найден${NC}"
    echo "Запустите скрипт из директории ~/insurance_broker"
    exit 1
fi

echo "1️⃣  Генерация паролей..."
echo ""

# Генерация паролей
DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
SECRET_KEY=$(openssl rand -base64 50 | tr -d "=+/" | cut -c1-50)

echo -e "${GREEN}✅ Пароли сгенерированы${NC}"
echo ""

# Создание backup старых файлов
if [ -f ".env.prod" ]; then
    echo "2️⃣  Создание backup старых файлов..."
    cp .env.prod .env.prod.backup.$(date +%Y%m%d_%H%M%S)
    echo -e "${GREEN}✅ Backup создан${NC}"
    echo ""
fi

# Создание .env.prod.db
echo "3️⃣  Создание .env.prod.db..."
cat > .env.prod.db << EOF
POSTGRES_DB=insurance_broker_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=${DB_PASSWORD}
EOF
echo -e "${GREEN}✅ .env.prod.db создан${NC}"
echo ""

# Создание .env.prod
echo "4️⃣  Создание .env.prod..."
cat > .env.prod << EOF
# Django
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=onbr.site,www.onbr.site

# Database
DB_NAME=insurance_broker_prod
DB_USER=postgres
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=db
DB_PORT=5432

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Email (console backend for now, update later for production)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EOF
echo -e "${GREEN}✅ .env.prod создан${NC}"
echo ""

# Установка правильных прав доступа
chmod 600 .env.prod .env.prod.db
echo -e "${GREEN}✅ Права доступа установлены (600)${NC}"
echo ""

# Перезапуск контейнеров
echo "5️⃣  Перезапуск контейнеров..."
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
echo -e "${GREEN}✅ Контейнеры перезапущены${NC}"
echo ""

# Ожидание запуска БД
echo "6️⃣  Ожидание запуска PostgreSQL..."
sleep 10
echo -e "${GREEN}✅ PostgreSQL готов${NC}"
echo ""

# Выполнение миграций
echo "7️⃣  Выполнение миграций..."
docker-compose -f docker-compose.prod.yml exec -T web python manage.py migrate --noinput
echo -e "${GREEN}✅ Миграции выполнены${NC}"
echo ""

# Сбор статики
echo "8️⃣  Сбор статических файлов..."
docker-compose -f docker-compose.prod.yml exec -T web python manage.py collectstatic --noinput --clear
echo -e "${GREEN}✅ Статика собрана${NC}"
echo ""

# Вывод информации
echo "===================================="
echo -e "${GREEN}🎉 Настройка завершена!${NC}"
echo ""
echo "📝 Сохраните эти данные в безопасном месте:"
echo ""
echo -e "${YELLOW}DB Password:${NC} ${DB_PASSWORD}"
echo -e "${YELLOW}Django SECRET_KEY:${NC} ${SECRET_KEY}"
echo ""
echo "⚠️  ВАЖНО: Сохраните эти пароли! Они больше не будут показаны."
echo ""
echo "📋 Следующие шаги:"
echo ""
echo "1. Создайте суперпользователя:"
echo "   docker-compose -f docker-compose.prod.yml exec web python manage.py createsuperuser"
echo ""
echo "2. Проверьте сайт:"
echo "   https://onbr.site"
echo ""
echo "3. Проверьте логи:"
echo "   docker-compose -f docker-compose.prod.yml logs"
echo ""
echo "4. Проверьте статус контейнеров:"
echo "   docker-compose -f docker-compose.prod.yml ps"
echo ""
