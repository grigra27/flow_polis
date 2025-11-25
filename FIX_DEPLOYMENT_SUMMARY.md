# Исправление Deployment - Итоговая инструкция

## ✅ Что исправлено

### GitHub Actions Workflow
Файл `.github/workflows/deploy.yml` теперь:
- **НЕ перезаписывает** `.env.prod` и `.env.prod.db`
- **НЕ удаляет** папку `certbot/` с SSL сертификатами
- **Проверяет** наличие этих файлов перед деплоем
- **Останавливает** деплой если файлы отсутствуют

### Новые файлы
- `scripts/diagnose-nginx.sh` - диагностика проблем nginx
- `nginx/default.conf.http-only` - временная конфигурация без HTTPS
- `docs/FIX_NGINX_RESTART.md` - подробная инструкция по nginx
- `docs/CREDENTIAL_RECOVERY.md` - как восстановить пароли
- `SERVER_COMMANDS.md` - все команды для сервера в одном месте

---

## 🔧 Что делать СЕЙЧАС на сервере

### 1. Диагностика nginx

```bash
ssh root@64.227.75.233
cd ~/insurance_broker
bash scripts/diagnose-nginx.sh
```

Это покажет:
- Статус nginx контейнера
- Логи ошибок
- Наличие SSL сертификатов
- Результат проверки конфигурации

### 2. Сохранить пароли

```bash
cd ~/insurance_broker

# Посмотреть пароли БД
cat .env.prod.db

# Посмотреть Django настройки
cat .env.prod
```

**⚠️ ВАЖНО: Скопируйте и сохраните эти пароли в безопасное место!**

### 3. Исправить nginx

#### Вариант A: Если сертификаты УЖЕ ЕСТЬ

Проверьте:
```bash
ls -la certbot/conf/live/onbr.site/
```

Если файлы есть, просто перезапустите nginx:
```bash
docker-compose -f docker-compose.prod.yml restart nginx
docker-compose -f docker-compose.prod.yml ps
```

#### Вариант B: Если сертификатов НЕТ

```bash
cd ~/insurance_broker

# 1. Временно отключить HTTPS
cp nginx/default.conf nginx/default.conf.backup
cp nginx/default.conf.http-only nginx/default.conf

# 2. Перезапустить nginx
docker-compose -f docker-compose.prod.yml restart nginx

# 3. Проверить что работает
docker-compose -f docker-compose.prod.yml ps
curl http://onbr.site/health/

# 4. Получить сертификаты
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email admin@onbr.site \
  --agree-tos \
  --no-eff-email \
  -d onbr.site \
  -d www.onbr.site

# 5. Проверить что сертификаты созданы
ls -la certbot/conf/live/onbr.site/

# 6. Включить HTTPS обратно
cp nginx/default.conf.backup nginx/default.conf

# 7. Перезапустить nginx
docker-compose -f docker-compose.prod.yml restart nginx

# 8. Проверить
docker-compose -f docker-compose.prod.yml ps
curl -I https://onbr.site
```

### 4. Проверить что все работает

```bash
# Все контейнеры должны быть "Up" и "healthy"
docker-compose -f docker-compose.prod.yml ps

# Проверить в браузере
# http://onbr.site или https://onbr.site
```

---

## 💻 Что делать ЛОКАЛЬНО

### 1. Закоммитить изменения

```bash
git add .github/workflows/deploy.yml
git add scripts/diagnose-nginx.sh
git add nginx/default.conf.http-only
git add docs/FIX_NGINX_RESTART.md
git add docs/CREDENTIAL_RECOVERY.md
git add DEPLOYMENT_QUICK_REFERENCE.md
git add SERVER_COMMANDS.md
git add FIX_DEPLOYMENT_SUMMARY.md
git commit -m "fix: preserve credentials and certificates during deployment"
git push origin main
```

### 2. Протестировать деплой

После того как nginx заработает на сервере:
- Сделайте небольшое изменение в коде
- Закоммитьте и запушьте в main
- GitHub Actions запустит деплой
- Проверьте что credentials НЕ были перезаписаны

---

## 📋 Checklist

- [ ] Запустил `diagnose-nginx.sh` на сервере
- [ ] Сохранил пароли из `.env.prod` и `.env.prod.db`
- [ ] Исправил nginx (HTTP-only или с сертификатами)
- [ ] Все контейнеры работают (status "Up")
- [ ] Сайт открывается в браузере
- [ ] Закоммитил изменения локально
- [ ] Протестировал деплой через GitHub Actions

---

## 🆘 Если что-то не работает

### Nginx перезапускается

```bash
# Посмотреть логи
docker-compose -f docker-compose.prod.yml logs nginx --tail 50

# Проверить конфигурацию
docker-compose -f docker-compose.prod.yml exec nginx nginx -t
```

### Web контейнер unhealthy

```bash
# Посмотреть логи
docker-compose -f docker-compose.prod.yml logs web --tail 50

# Перезапустить
docker-compose -f docker-compose.prod.yml restart web
```

### База данных не работает

```bash
# Посмотреть логи
docker-compose -f docker-compose.prod.yml logs db --tail 50

# Проверить подключение
docker-compose -f docker-compose.prod.yml exec web python manage.py dbshell
```

---

## 📚 Полезные ссылки

- [SERVER_COMMANDS.md](SERVER_COMMANDS.md) - все команды для сервера
- [docs/FIX_NGINX_RESTART.md](docs/FIX_NGINX_RESTART.md) - подробно про nginx
- [docs/CREDENTIAL_RECOVERY.md](docs/CREDENTIAL_RECOVERY.md) - про пароли
- [DEPLOYMENT_QUICK_REFERENCE.md](DEPLOYMENT_QUICK_REFERENCE.md) - быстрая справка

---

## 🎯 Результат

После выполнения всех шагов:

✅ Credentials сохраняются между деплоями  
✅ SSL сертификаты не удаляются  
✅ Nginx работает стабильно  
✅ Сайт доступен по HTTPS  
✅ GitHub Actions деплоит безопасно  

**Ваши данные в безопасности! 🔒**
