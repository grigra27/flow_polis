# Первоначальное развёртывание на Timeweb

Этот документ описывает полный процесс первого деплоя на production-сервер.

**Текущий сервер:** Timeweb VPS, `~/insurance_broker/`
**Домен:** `polis.insflow.ru`
**CI/CD:** GitHub Actions → rsync → docker-compose (v1, дефис)

При последующих деплоях достаточно просто пушить в `main` — GitHub Actions сделает всё автоматически. Этот гайд нужен только при первом запуске или при переезде на новый сервер.

---

## Предварительные требования

- [ ] SSH-доступ к серверу настроен
- [ ] Docker и `docker-compose` (v1) установлены на сервере
- [ ] Firewall открывает порты 22, 80, 443
- [ ] DNS-запись `polis.insflow.ru` указывает на IP сервера
- [ ] GitHub Secrets настроены (см. [GITHUB_SECRETS_SETUP.md](./GITHUB_SECRETS_SETUP.md))

---

## Шаг 1: Первичная настройка сервера

```bash
ssh root@<SERVER_IP>
mkdir -p ~/insurance_broker/logs ~/insurance_broker/certbot/conf ~/insurance_broker/certbot/www
cd ~/insurance_broker
```

Скопировать код на сервер (если CI ещё не настроен):
```bash
# На локальной машине
rsync -avz --exclude='.git' --exclude='venv' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='.env*' --exclude='db.sqlite3' \
  ./ root@<SERVER_IP>:~/insurance_broker/
```

---

## Шаг 2: Создать .env.prod

```bash
cd ~/insurance_broker
cp .env.prod.example .env.prod
nano .env.prod
```

Обязательные переменные:

```bash
SECRET_KEY=<сгенерировать: openssl rand -base64 50>
DEBUG=False
ALLOWED_HOSTS=polis.insflow.ru

# Postgres (используются и Django, и postgres-контейнером)
POSTGRES_DB=insurance_broker_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<сгенерировать: openssl rand -base64 32>

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Telegram / VK (можно добавить позже)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_ENABLED=false
```

Полный список переменных — в [ENVIRONMENT_VARIABLES.md](./ENVIRONMENT_VARIABLES.md).

```bash
chmod 600 .env.prod
```

---

## Шаг 3: Запустить контейнеры (без SSL)

```bash
cd ~/insurance_broker

# nginx пока запустить без SSL (сертификата ещё нет)
cp nginx/default.conf nginx/default.conf.ssl
cp nginx/default.conf.initial nginx/default.conf

set -a; source .env.prod; set +a
docker-compose -f docker-compose.prod.yml up -d --build

# Проверить статус
docker-compose -f docker-compose.prod.yml ps
```

Все контейнеры должны быть `Up`. Проверить:
```bash
curl http://polis.insflow.ru/health/
```

---

## Шаг 4: Получить SSL-сертификат

> Классическая проблема «курица и яйцо»: nginx не стартует без сертификата, certbot не получает сертификат без работающего nginx на 80 порту. Шаг 3 решает это через временную конфигурацию без SSL.

```bash
cd ~/insurance_broker

# Убедиться что DNS уже указывает на сервер
nslookup polis.insflow.ru

# Получить сертификат
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@insflow.ru \
    --agree-tos \
    --no-eff-email \
    -d polis.insflow.ru

# Проверить что файлы появились
docker-compose -f docker-compose.prod.yml exec nginx \
    ls /etc/letsencrypt/live/polis.insflow.ru/
```

Должны появиться: `cert.pem`, `chain.pem`, `fullchain.pem`, `privkey.pem`.

---

## Шаг 5: Включить SSL

```bash
# Вернуть SSL-конфигурацию
cp nginx/default.conf.ssl nginx/default.conf

docker-compose -f docker-compose.prod.yml restart nginx

# Проверить HTTPS
curl -I https://polis.insflow.ru
curl -I http://polis.insflow.ru  # должен редиректить на HTTPS
```

---

## Шаг 6: Создать суперпользователя

```bash
docker-compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

---

## Шаг 7: Настроить GitHub Actions для автодеплоя

Добавить Secrets в репозитории (Settings → Secrets → Actions):

| Secret | Значение |
|--------|----------|
| `SSH_PRIVATE_KEY` | Приватный SSH-ключ для доступа к серверу |
| `DROPLET_HOST` | IP-адрес сервера |
| `DROPLET_USER` | SSH-пользователь (обычно `root`) |
| `SSH_PORT` | SSH-порт (если не 22) |

После этого любой push в `main` запустит деплой автоматически.

---

## Финальная проверка

```bash
# Все контейнеры работают
docker-compose -f docker-compose.prod.yml ps

# Логи без ошибок
docker-compose -f docker-compose.prod.yml logs --tail=20 web

# Сайт доступен
curl -I https://polis.insflow.ru
curl -I https://polis.insflow.ru/admin/
```

---

## Устранение неполадок

**Nginx не запускается:**
```bash
docker-compose -f docker-compose.prod.yml logs nginx
docker-compose -f docker-compose.prod.yml exec nginx nginx -t
```

**Certbot не может получить сертификат:**
```bash
# Проверить DNS
nslookup polis.insflow.ru

# Проверить что порт 80 доступен
curl http://polis.insflow.ru/.well-known/acme-challenge/test

# Логи certbot
docker-compose -f docker-compose.prod.yml logs certbot
```

**Контейнеры не стартуют (ошибка при миграции):**
```bash
docker logs insurance_broker_web
```

**Статические файлы не загружаются:**
```bash
docker-compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput --clear
docker-compose -f docker-compose.prod.yml restart nginx
```

---

## Следующие шаги

- Настроить Telegram/VK уведомления: [TELEGRAM_NOTIFICATIONS.md](./TELEGRAM_NOTIFICATIONS.md)
- Настроить бэкапы: [BACKUP_RESTORE.md](./BACKUP_RESTORE.md)
- Изучить мониторинг: [MONITORING.md](./MONITORING.md)
