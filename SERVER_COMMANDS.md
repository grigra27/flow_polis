# Команды для выполнения на сервере

## 1. Диагностика nginx

```bash
cd ~/insurance_broker
bash scripts/diagnose-nginx.sh
```

## 2. Посмотреть текущие пароли

```bash
cd ~/insurance_broker

# Из файлов
cat .env.prod.db
cat .env.prod

# Из контейнеров
docker-compose -f docker-compose.prod.yml exec db env | grep POSTGRES
docker-compose -f docker-compose.prod.yml exec web env | grep DB_
```

## 3. Временно отключить HTTPS (если нет сертификатов)

```bash
cd ~/insurance_broker

# Бэкап текущей конфигурации
cp nginx/default.conf nginx/default.conf.backup

# Использовать HTTP-only
cp nginx/default.conf.http-only nginx/default.conf

# Перезапустить nginx
docker-compose -f docker-compose.prod.yml restart nginx

# Проверить статус
docker-compose -f docker-compose.prod.yml ps
```

## 4. Получить SSL сертификаты

```bash
cd ~/insurance_broker

# Получить сертификаты (nginx должен работать на HTTP)
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

# Восстановить HTTPS конфигурацию
cp nginx/default.conf.backup nginx/default.conf

# Перезапустить nginx
docker-compose -f docker-compose.prod.yml restart nginx
```

## 5. Проверить статус всех контейнеров

```bash
cd ~/insurance_broker
docker-compose -f docker-compose.prod.yml ps
```

## 6. Посмотреть логи

```bash
cd ~/insurance_broker

# Nginx
docker-compose -f docker-compose.prod.yml logs nginx --tail 50

# Web
docker-compose -f docker-compose.prod.yml logs web --tail 50

# Database
docker-compose -f docker-compose.prod.yml logs db --tail 50

# Все контейнеры
docker-compose -f docker-compose.prod.yml logs --tail 50
```

## 7. Перезапустить контейнеры

```bash
cd ~/insurance_broker

# Один контейнер
docker-compose -f docker-compose.prod.yml restart nginx
docker-compose -f docker-compose.prod.yml restart web

# Все контейнеры
docker-compose -f docker-compose.prod.yml restart

# Полный перезапуск (down + up)
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

## 8. Проверить работоспособность

```bash
# Проверить что nginx отвечает
curl -I http://onbr.site

# Проверить HTTPS (если сертификаты установлены)
curl -I https://onbr.site

# Проверить health endpoint
curl http://onbr.site/health/

# Проверить что приложение работает
curl http://onbr.site/
```

## Быстрая последовательность для исправления nginx

```bash
cd ~/insurance_broker

# 1. Диагностика
bash scripts/diagnose-nginx.sh

# 2. Если нет сертификатов - временно HTTP
cp nginx/default.conf nginx/default.conf.backup
cp nginx/default.conf.http-only nginx/default.conf
docker-compose -f docker-compose.prod.yml restart nginx

# 3. Проверить что работает
docker-compose -f docker-compose.prod.yml ps
curl http://onbr.site/health/

# 4. Получить сертификаты
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot --webroot-path=/var/www/certbot \
  --email admin@onbr.site --agree-tos --no-eff-email \
  -d onbr.site -d www.onbr.site

# 5. Включить HTTPS
cp nginx/default.conf.backup nginx/default.conf
docker-compose -f docker-compose.prod.yml restart nginx

# 6. Проверить
docker-compose -f docker-compose.prod.yml ps
curl -I https://onbr.site
```
