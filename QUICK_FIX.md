# Быстрое решение проблемы первого деплоя

## Проблема
Nginx не запускается при первом деплое из-за отсутствия SSL сертификатов.

## Решение

Подключитесь к серверу и выполните:

```bash
cd ~/insurance_broker
git pull origin main
./scripts/setup-ssl.sh
```

Скрипт автоматически:
- Переключит nginx на конфигурацию без SSL
- Получит SSL сертификат
- Включит SSL конфигурацию
- Перезапустит nginx

## Проверка

```bash
# Проверьте что все контейнеры запущены
docker-compose -f docker-compose.prod.yml ps

# Проверьте HTTPS
curl https://polis.insflow.ru/health/
```

## Подробная документация

См. [docs/FIRST_DEPLOYMENT.md](docs/FIRST_DEPLOYMENT.md)

## Если автоматический скрипт не работает

Выполните вручную:

```bash
cd ~/insurance_broker

# 1. Переключитесь на конфигурацию без SSL
cp nginx/default.conf nginx/default.conf.ssl
cp nginx/default.conf.initial nginx/default.conf

# 2. Перезапустите nginx
docker-compose -f docker-compose.prod.yml restart nginx

# 3. Получите сертификат
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@insflow.ru \
    --agree-tos \
    --no-eff-email \
    -d polis.insflow.ru

# 4. Включите SSL
cp nginx/default.conf.ssl nginx/default.conf
docker-compose -f docker-compose.prod.yml restart nginx
```

## Подробная документация

См. [docs/FIRST_DEPLOYMENT.md](docs/FIRST_DEPLOYMENT.md)
