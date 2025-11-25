# Руководство по первоначальному развертыванию

Это краткое руководство описывает процесс первоначального развертывания приложения на Digital Ocean Droplet.

## Предварительные требования

Перед началом убедитесь, что:

1. ✅ Создан Droplet на Digital Ocean (см. [DROPLET_SETUP.md](./DROPLET_SETUP.md))
2. ✅ Установлены Docker и Docker Compose на Droplet
3. ✅ Настроен firewall (порты 22, 80, 443)
4. ✅ Настроены SSH ключи для доступа к Droplet
5. ✅ DNS настроен и указывает на IP Droplet (см. [DNS_SETUP.md](./DNS_SETUP.md))

## Быстрое развертывание

### Вариант 1: Автоматизированный скрипт (Рекомендуется)

Используйте автоматизированный скрипт для развертывания:

```bash
# Из корневой директории проекта на локальной машине
export DROPLET_IP="YOUR_DROPLET_IP"
export DROPLET_USER="root"

./scripts/initial-deploy.sh
```

Скрипт выполнит все необходимые шаги автоматически:
- Копирование файлов на Droplet
- Создание .env.prod с production переменными
- Запуск docker-compose
- Получение SSL сертификата через Let's Encrypt
- Обновление Nginx конфигурации для HTTPS
- Проверку доступности сайта

### Вариант 2: Ручное развертывание

Если вы предпочитаете ручное развертывание, следуйте шагам ниже.

## Шаг 1: Копирование файлов на Droplet

### 1.1 Создание директории приложения

```bash
# SSH в Droplet
ssh root@YOUR_DROPLET_IP

# Создание директории
mkdir -p /opt/insurance_broker
cd /opt/insurance_broker

# Создание поддиректорий
mkdir -p nginx certbot/conf certbot/www logs scripts
```

### 1.2 Копирование файлов с локальной машины

```bash
# На локальной машине (из корня проекта)
export DROPLET_IP="YOUR_DROPLET_IP"

# Используя rsync (рекомендуется)
rsync -avz --progress \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='db.sqlite3' \
  ./ root@$DROPLET_IP:/opt/insurance_broker/

# Или используя scp
scp -r apps config templates static fixtures nginx scripts \
  Dockerfile docker-compose.prod.yml requirements.txt \
  requirements.prod.txt manage.py entrypoint.sh .dockerignore \
  create_superuser.py root@$DROPLET_IP:/opt/insurance_broker/
```

## Шаг 2: Создание .env.prod с production переменными

### 2.1 Генерация секретных ключей

```bash
# SSH в Droplet
ssh root@YOUR_DROPLET_IP
cd /opt/insurance_broker

# Генерация SECRET_KEY
SECRET_KEY=$(openssl rand -base64 50)

# Генерация пароля базы данных
DB_PASSWORD=$(openssl rand -base64 32)

echo "Generated credentials (save these securely!):"
echo "SECRET_KEY: $SECRET_KEY"
echo "DB_PASSWORD: $DB_PASSWORD"
```

### 2.2 Создание .env.prod

```bash
cat > .env.prod << EOF
# Django Core Settings
SECRET_KEY=$SECRET_KEY
DEBUG=False
ALLOWED_HOSTS=onbr.site,www.onbr.site

# Database Configuration
DB_NAME=insurance_broker_prod
DB_USER=postgres
DB_PASSWORD=$DB_PASSWORD
DB_HOST=db
DB_PORT=5432

# Celery Configuration
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Email Configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
DEFAULT_FROM_EMAIL=noreply@onbr.site

# Security Settings
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_CONTENT_TYPE_NOSNIFF=True
SECURE_BROWSER_XSS_FILTER=True
X_FRAME_OPTIONS=DENY

# Static and Media Files
STATIC_ROOT=/app/staticfiles
MEDIA_ROOT=/app/media
STATIC_URL=/static/
MEDIA_URL=/media/

# Logging
LOG_LEVEL=INFO
EOF
```

### 2.3 Создание .env.prod.db

```bash
cat > .env.prod.db << EOF
POSTGRES_DB=insurance_broker_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$DB_PASSWORD
EOF
```

### 2.4 Установка правильных прав доступа

```bash
chmod 600 .env.prod .env.prod.db
```

**ВАЖНО:** Сохраните сгенерированные пароли в безопасном месте!

## Шаг 3: Запуск docker-compose

### 3.1 Первоначальный запуск

```bash
# На Droplet
cd /opt/insurance_broker

# Запуск всех сервисов
docker compose -f docker-compose.prod.yml up -d

# Проверка статуса
docker compose -f docker-compose.prod.yml ps
```

Ожидаемый вывод - все контейнеры в статусе "Up":
```
NAME                    STATUS
insurance_broker_web    Up
insurance_broker_db     Up (healthy)
insurance_broker_redis  Up (healthy)
insurance_broker_nginx  Up
insurance_broker_celery_worker  Up
insurance_broker_celery_beat    Up
```

### 3.2 Просмотр логов

```bash
# Все сервисы
docker compose -f docker-compose.prod.yml logs -f

# Конкретный сервис
docker compose -f docker-compose.prod.yml logs -f web
```

### 3.3 Выполнение миграций

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput
```

### 3.4 Сбор статических файлов

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput --clear
```

## Шаг 4: Получение SSL сертификата через Let's Encrypt

### 4.1 Проверка DNS

Перед получением SSL сертификата убедитесь, что DNS настроен правильно:

```bash
# На локальной машине или Droplet
dig onbr.site +short
dig www.onbr.site +short

# Должен вернуть IP адрес вашего Droplet
```

### 4.2 Запуск скрипта инициализации SSL

```bash
# На Droplet
cd /opt/insurance_broker

# Сделать скрипт исполняемым
chmod +x scripts/init-letsencrypt.sh

# Запустить скрипт
./scripts/init-letsencrypt.sh
```

Скрипт выполнит следующие действия:
1. Проверит наличие существующих сертификатов
2. Настроит временную Nginx конфигурацию (без SSL)
3. Запустит certbot для получения сертификата
4. Обновит Nginx конфигурацию для использования SSL
5. Перезапустит Nginx

### 4.3 Тестирование с staging сервером (опционально)

Если вы хотите протестировать процесс без использования лимитов Let's Encrypt:

```bash
STAGING=1 ./scripts/init-letsencrypt.sh
```

### 4.4 Проверка сертификата

```bash
# Проверка файлов сертификата
ls -la certbot/conf/live/onbr.site/

# Проверка срока действия
docker compose -f docker-compose.prod.yml run --rm certbot certificates
```

## Шаг 5: Обновление Nginx конфигурации для HTTPS

Скрипт `init-letsencrypt.sh` автоматически обновляет конфигурацию. Если нужно сделать это вручную:

### 5.1 Проверка конфигурации Nginx

```bash
docker compose -f docker-compose.prod.yml exec nginx nginx -t
```

Ожидаемый вывод:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### 5.2 Перезапуск Nginx

```bash
docker compose -f docker-compose.prod.yml restart nginx
```

## Шаг 6: Проверка доступности сайта

### 6.1 Проверка HTTP редиректа

```bash
# Должен вернуть 301 или 302 редирект на HTTPS
curl -I http://onbr.site
```

### 6.2 Проверка HTTPS

```bash
# Должен вернуть 200 OK
curl -I https://onbr.site
```

### 6.3 Проверка в браузере

Откройте в браузере:
- https://onbr.site - главная страница
- https://onbr.site/admin/ - админ панель

Проверьте, что:
- ✅ Сайт открывается по HTTPS
- ✅ Нет предупреждений о сертификате
- ✅ HTTP автоматически редиректит на HTTPS
- ✅ Статические файлы загружаются корректно

### 6.4 Проверка SSL сертификата

```bash
# Проверка SSL сертификата
openssl s_client -connect onbr.site:443 -servername onbr.site < /dev/null | grep -A 2 "Verify return code"
```

Ожидаемый вывод:
```
Verify return code: 0 (ok)
```

## Шаг 7: Создание суперпользователя Django

```bash
# На Droplet
cd /opt/insurance_broker

docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Введите:
# - Username
# - Email
# - Password (дважды)
```

## Шаг 8: Загрузка начальных данных (опционально)

Если у вас есть fixtures с начальными данными:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py loaddata fixtures/initial_data.json
```

## Проверка развертывания

### Контрольный список

- [ ] Все контейнеры запущены и работают
- [ ] База данных доступна и миграции применены
- [ ] Статические файлы собраны и отдаются Nginx
- [ ] SSL сертификат получен и работает
- [ ] HTTP редиректит на HTTPS
- [ ] Сайт доступен по https://onbr.site
- [ ] Админ панель доступна по https://onbr.site/admin/
- [ ] Создан суперпользователь
- [ ] Celery worker и beat запущены

### Команды для проверки

```bash
# Статус контейнеров
docker compose -f docker-compose.prod.yml ps

# Проверка логов
docker compose -f docker-compose.prod.yml logs --tail=50

# Проверка подключения к БД
docker compose -f docker-compose.prod.yml exec web python manage.py check --database default

# Проверка Celery
docker compose -f docker-compose.prod.yml exec celery_worker celery -A config inspect ping

# Использование ресурсов
docker stats --no-stream
```

## Troubleshooting

### Проблема: Контейнеры не запускаются

```bash
# Проверка логов
docker compose -f docker-compose.prod.yml logs

# Пересборка образов
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

### Проблема: Не удается получить SSL сертификат

Проверьте:
1. DNS указывает на правильный IP: `dig onbr.site +short`
2. Firewall разрешает порты 80 и 443: `sudo ufw status`
3. Nginx запущен и доступен: `curl http://localhost`

Попробуйте с staging сервером:
```bash
STAGING=1 ./scripts/init-letsencrypt.sh
```

### Проблема: Статические файлы не загружаются

```bash
# Пересобрать статику
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput --clear

# Проверить права доступа
docker compose -f docker-compose.prod.yml exec web ls -la /app/staticfiles/

# Перезапустить Nginx
docker compose -f docker-compose.prod.yml restart nginx
```

### Проблема: Ошибки подключения к базе данных

```bash
# Проверить статус PostgreSQL
docker compose -f docker-compose.prod.yml ps db

# Проверить логи
docker compose -f docker-compose.prod.yml logs db

# Проверить переменные окружения
docker compose -f docker-compose.prod.yml exec web env | grep DB_
```

## Следующие шаги

После успешного развертывания:

1. **Настройте GitHub Secrets для CI/CD** (Task 20)
   - SSH_PRIVATE_KEY
   - DROPLET_HOST
   - DROPLET_USER

2. **Протестируйте автоматический деплой** (Task 21)
   - Сделайте тестовый коммит
   - Проверьте GitHub Actions

3. **Настройте мониторинг**
   - Настройте алерты для критических ошибок
   - Настройте логирование

4. **Настройте бэкапы**
   - Автоматические бэкапы базы данных
   - Бэкапы медиа файлов

## Полезные команды

### Управление контейнерами

```bash
# Перезапуск всех сервисов
docker compose -f docker-compose.prod.yml restart

# Перезапуск конкретного сервиса
docker compose -f docker-compose.prod.yml restart web

# Остановка всех сервисов
docker compose -f docker-compose.prod.yml down

# Запуск с пересборкой
docker compose -f docker-compose.prod.yml up -d --build
```

### Просмотр логов

```bash
# Все логи
docker compose -f docker-compose.prod.yml logs -f

# Последние 100 строк
docker compose -f docker-compose.prod.yml logs --tail=100

# Конкретный сервис
docker compose -f docker-compose.prod.yml logs -f web
```

### Выполнение команд Django

```bash
# Миграции
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Создание миграций
docker compose -f docker-compose.prod.yml exec web python manage.py makemigrations

# Django shell
docker compose -f docker-compose.prod.yml exec web python manage.py shell

# Проверка системы
docker compose -f docker-compose.prod.yml exec web python manage.py check
```

### Бэкапы

```bash
# Бэкап базы данных
docker compose -f docker-compose.prod.yml exec db pg_dump -U postgres insurance_broker_prod > backup_$(date +%Y%m%d).sql

# Восстановление
cat backup_20240101.sql | docker compose -f docker-compose.prod.yml exec -T db psql -U postgres insurance_broker_prod
```

## Дополнительные ресурсы

- [Полное руководство по развертыванию](./DEPLOYMENT.md)
- [Настройка Droplet](./DROPLET_SETUP.md)
- [Настройка DNS](./DNS_SETUP.md)
- [Резервное копирование и восстановление](./BACKUP_RESTORE.md)
- [Мониторинг](./MONITORING.md)

## Поддержка

Если возникли проблемы:
1. Проверьте раздел Troubleshooting выше
2. Просмотрите логи контейнеров
3. Обратитесь к полной документации в docs/DEPLOYMENT.md

---

**Последнее обновление:** 2024
**Версия:** 1.0
