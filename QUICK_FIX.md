# Быстрое исправление nginx - Шпаргалка

## На сервере выполните:

```bash
ssh root@64.227.75.233
cd ~/insurance_broker

# 1. Диагностика
bash scripts/diagnose-nginx.sh

# 2. Если нет сертификатов - временно HTTP
cp nginx/default.conf nginx/default.conf.backup
cp nginx/default.conf.http-only nginx/default.conf
docker-compose -f docker-compose.prod.yml restart nginx

# 3. Проверить
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

# 6. Готово!
docker-compose -f docker-compose.prod.yml ps
```

## Сохранить пароли:

```bash
cat .env.prod.db
cat .env.prod
```

**Скопируйте и сохраните в password manager!**

---

Подробнее: [FIX_DEPLOYMENT_SUMMARY.md](FIX_DEPLOYMENT_SUMMARY.md)
