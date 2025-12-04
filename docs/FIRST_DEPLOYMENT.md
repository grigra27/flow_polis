# Руководство по первому деплою

## Проблема

При первом деплое nginx не может запуститься, потому что в конфигурации указаны SSL сертификаты, которых еще нет. Это классическая проблема "курицы и яйца":
- Для получения SSL сертификата нужен работающий nginx на порту 80
- Но nginx не запускается без SSL сертификатов

## Решение

Используйте поэтапный подход:

### Вариант 1: Автоматический (Рекомендуется)

```bash
# На сервере выполните:
cd ~/insurance_broker
./scripts/setup-ssl.sh
```

Скрипт автоматически:
1. Переключит nginx на конфигурацию без SSL
2. Перезапустит nginx
3. Получит SSL сертификат через certbot
4. Переключит nginx обратно на конфигурацию с SSL
5. Перезапустит nginx с SSL

### Вариант 2: Ручной

#### Шаг 1: Подготовка конфигурации

```bash
cd ~/insurance_broker

# Сохраните SSL конфигурацию
cp nginx/default.conf nginx/default.conf.ssl

# Используйте начальную конфигурацию без SSL
cp nginx/default.conf.initial nginx/default.conf
```

#### Шаг 2: Запуск без SSL

```bash
# Перезапустите nginx с новой конфигурацией
docker-compose -f docker-compose.prod.yml restart nginx

# Проверьте что nginx запустился
docker-compose -f docker-compose.prod.yml ps nginx

# Проверьте доступность
curl http://polis.insflow.ru/health/
```

#### Шаг 3: Получение SSL сертификата

```bash
# Получите сертификат
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@insflow.ru \
    --agree-tos \
    --no-eff-email \
    -d polis.insflow.ru

# Проверьте что сертификат получен
docker-compose -f docker-compose.prod.yml exec nginx \
    ls -la /etc/letsencrypt/live/polis.insflow.ru/
```

Вы должны увидеть файлы:
- `cert.pem`
- `chain.pem`
- `fullchain.pem`
- `privkey.pem`

#### Шаг 4: Включение SSL

```bash
# Верните SSL конфигурацию
cp nginx/default.conf.ssl nginx/default.conf

# Перезапустите nginx
docker-compose -f docker-compose.prod.yml restart nginx

# Проверьте HTTPS
curl https://polis.insflow.ru/health/
```

## Проверка результата

После успешного выполнения:

```bash
# HTTP должен редиректить на HTTPS
curl -I http://polis.insflow.ru

# HTTPS должен работать
curl -I https://polis.insflow.ru

# Проверьте все контейнеры
docker-compose -f docker-compose.prod.yml ps
```

Все контейнеры должны быть в состоянии "Up".

## Устранение проблем

### Nginx не запускается

```bash
# Проверьте логи
docker-compose -f docker-compose.prod.yml logs nginx

# Проверьте конфигурацию
docker-compose -f docker-compose.prod.yml exec nginx nginx -t
```

### Certbot не может получить сертификат

```bash
# Убедитесь что DNS настроен
nslookup polis.insflow.ru

# Проверьте доступность порта 80
curl http://polis.insflow.ru/.well-known/acme-challenge/test

# Проверьте логи certbot
docker-compose -f docker-compose.prod.yml logs certbot
```

### SSL не работает после получения сертификата

```bash
# Проверьте что файлы сертификата существуют
docker-compose -f docker-compose.prod.yml exec nginx \
    ls -la /etc/letsencrypt/live/polis.insflow.ru/

# Проверьте конфигурацию nginx
docker-compose -f docker-compose.prod.yml exec nginx nginx -t

# Перезапустите nginx
docker-compose -f docker-compose.prod.yml restart nginx
```

## Следующие шаги

После успешного первого деплоя:

1. Проверьте работу приложения: https://polis.insflow.ru
2. Проверьте админ-панель: https://polis.insflow.ru/admin/
3. Проверьте логи всех сервисов
4. Настройте мониторинг
5. Создайте резервную копию

См. [POST_MIGRATION_CHECKLIST.md](../POST_MIGRATION_CHECKLIST.md) для полного списка проверок.
