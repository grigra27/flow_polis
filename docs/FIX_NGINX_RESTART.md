# Исправление проблемы с перезапуском nginx

## Проблема

Nginx контейнер постоянно перезапускается:
```
insurance_broker_nginx  nginx:alpine  ...  Restarting (1) 45 seconds ago
```

## Причина

Скорее всего nginx не может найти SSL сертификаты, которые указаны в конфигурации:
```
ssl_certificate /etc/letsencrypt/live/onbr.site/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/onbr.site/privkey.pem;
```

## Диагностика

На сервере запустите:

```bash
cd ~/insurance_broker
./scripts/diagnose-nginx.sh
```

Это покажет:
- Статус nginx контейнера
- Логи ошибок
- Наличие SSL сертификатов
- Результат проверки конфигурации

## Решение 1: Временно отключить HTTPS (быстрое)

Если сертификаты отсутствуют, временно используйте HTTP-only конфигурацию:

```bash
# На сервере
cd ~/insurance_broker

# Сделать бэкап текущей конфигурации
cp nginx/default.conf nginx/default.conf.backup

# Использовать HTTP-only конфигурацию
cp nginx/default.conf.http-only nginx/default.conf

# Перезапустить nginx
docker-compose -f docker-compose.prod.yml restart nginx

# Проверить статус
docker-compose -f docker-compose.prod.yml ps nginx
```

Теперь сайт должен работать на http://onbr.site

## Решение 2: Получить SSL сертификаты

После того как nginx работает на HTTP:

```bash
# Получить сертификаты
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email admin@onbr.site \
  --agree-tos \
  --no-eff-email \
  -d onbr.site \
  -d www.onbr.site

# Проверить что сертификаты созданы
ls -la certbot/conf/live/onbr.site/

# Восстановить полную конфигурацию с HTTPS
cp nginx/default.conf.backup nginx/default.conf

# Перезапустить nginx
docker-compose -f docker-compose.prod.yml restart nginx

# Проверить статус
docker-compose -f docker-compose.prod.yml ps
```

Теперь сайт должен работать на https://onbr.site

## Решение 3: Если сертификаты уже есть

Если сертификаты существуют, но nginx все равно падает:

```bash
# Проверить логи nginx
docker-compose -f docker-compose.prod.yml logs nginx --tail 50

# Проверить конфигурацию nginx
docker-compose -f docker-compose.prod.yml exec nginx nginx -t

# Если есть синтаксическая ошибка, исправьте nginx/default.conf
# и перезапустите:
docker-compose -f docker-compose.prod.yml restart nginx
```

## Решение 4: Если web контейнер unhealthy

Если nginx работает, но web контейнер unhealthy:

```bash
# Проверить логи web
docker-compose -f docker-compose.prod.yml logs web --tail 50

# Проверить что gunicorn запущен
docker-compose -f docker-compose.prod.yml exec web ps aux | grep gunicorn

# Перезапустить web
docker-compose -f docker-compose.prod.yml restart web

# Подождать 30 секунд и проверить статус
sleep 30
docker-compose -f docker-compose.prod.yml ps
```

## Проверка работоспособности

После исправления проверьте:

```bash
# 1. Все контейнеры работают
docker-compose -f docker-compose.prod.yml ps

# 2. Nginx отвечает
curl -I http://onbr.site

# 3. HTTPS работает (если сертификаты установлены)
curl -I https://onbr.site

# 4. Приложение отвечает
curl http://onbr.site/health/
```

## Автоматическое обновление сертификатов

Certbot контейнер автоматически обновляет сертификаты каждые 12 часов.

Проверить логи certbot:
```bash
docker-compose -f docker-compose.prod.yml logs certbot
```

## Важно

После исправления nginx, **не забудьте закоммитить изменения** если вы меняли конфигурацию:

```bash
# Локально
git add nginx/default.conf
git commit -m "fix: nginx configuration"
git push origin main
```

Но помните: GitHub Actions теперь **НЕ перезаписывает** сертификаты, так что они сохранятся при следующем деплое!
