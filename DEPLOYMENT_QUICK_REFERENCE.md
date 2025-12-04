# Быстрая справка по развертыванию

## ⚠️ ВАЖНО: Credentials и Сертификаты

GitHub Actions workflow **НЕ перезаписывает**:
- `.env.prod` - ваши production credentials
- `.env.prod.db` - пароли базы данных
- `certbot/` - SSL сертификаты Let's Encrypt

Эти файлы сохраняются между деплоями!

**Если забыли пароли:** `./scripts/show-production-credentials.sh`
**Подробнее:** [docs/CREDENTIAL_RECOVERY.md](docs/CREDENTIAL_RECOVERY.md)

---

## Первоначальное развертывание (Task 19)

### Быстрый старт

```bash
# IP уже прописан по умолчанию: 109.68.215.223
# Просто запустите скрипт:
./scripts/initial-deploy.sh

# Или явно укажите IP (если нужно переопределить):
export DROPLET_IP="109.68.215.223"
./scripts/initial-deploy.sh
```

Скрипт выполнит все необходимые шаги автоматически (~15-20 минут).

---

## Предварительные требования

✅ Droplet создан и настроен (Task 17)
✅ DNS настроен для polis.insflow.ru (Task 18)
✅ SSH ключи настроены
✅ Firewall разрешает порты 22, 80, 443

---

## Основные команды

### Подключение к Droplet

```bash
ssh root@109.68.215.223
cd /opt/insurance_broker
```

### Управление контейнерами

```bash
# Статус всех контейнеров
docker compose -f docker-compose.prod.yml ps

# Запуск
docker compose -f docker-compose.prod.yml up -d

# Остановка
docker compose -f docker-compose.prod.yml down

# Перезапуск
docker compose -f docker-compose.prod.yml restart [service]

# Логи
docker compose -f docker-compose.prod.yml logs -f [service]
```

### Django команды

```bash
# Миграции
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Сбор статики
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Создание суперпользователя
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Django shell
docker compose -f docker-compose.prod.yml exec web python manage.py shell
```

### SSL сертификат

```bash
# Получение сертификата
./scripts/init-letsencrypt.sh

# Обновление сертификата
docker compose -f docker-compose.prod.yml run --rm certbot renew
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload

# Проверка сертификата
docker compose -f docker-compose.prod.yml run --rm certbot certificates
```

### Бэкапы

```bash
# Бэкап базы данных
docker compose -f docker-compose.prod.yml exec db pg_dump -U postgres insurance_broker_prod > backup_$(date +%Y%m%d).sql

# Восстановление
cat backup_20240101.sql | docker compose -f docker-compose.prod.yml exec -T db psql -U postgres insurance_broker_prod
```

---

## Проверка работоспособности

### Быстрая проверка

```bash
# Статус контейнеров
docker compose -f docker-compose.prod.yml ps

# Проверка сайта
curl -I https://polis.insflow.ru

# Проверка HTTP редиректа
curl -I http://polis.insflow.ru
```

### Детальная проверка

```bash
# База данных
docker compose -f docker-compose.prod.yml exec web python manage.py check --database default

# Celery
docker compose -f docker-compose.prod.yml exec celery_worker celery -A config inspect ping

# Использование ресурсов
docker stats --no-stream

# Логи
docker compose -f docker-compose.prod.yml logs --tail=50
```

---

## Troubleshooting

### Контейнер не запускается

```bash
# Проверить логи
docker compose -f docker-compose.prod.yml logs [service]

# Пересобрать образ
docker compose -f docker-compose.prod.yml build --no-cache [service]
docker compose -f docker-compose.prod.yml up -d [service]
```

### Проблемы с SSL

```bash
# Проверить DNS
dig polis.insflow.ru +short

# Проверить firewall
sudo ufw status

# Попробовать staging
STAGING=1 ./scripts/init-letsencrypt.sh
```

### Статика не загружается

```bash
# Пересобрать статику
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput --clear

# Перезапустить Nginx
docker compose -f docker-compose.prod.yml restart nginx
```

### Ошибки базы данных

```bash
# Проверить статус
docker compose -f docker-compose.prod.yml ps db

# Проверить логи
docker compose -f docker-compose.prod.yml logs db

# Проверить переменные
docker compose -f docker-compose.prod.yml exec web env | grep DB_
```

---

## Важные пути

| Что | Путь |
|-----|------|
| Приложение | `/opt/insurance_broker` |
| Логи | `/opt/insurance_broker/logs` |
| SSL сертификаты | `/opt/insurance_broker/certbot/conf` |
| Nginx конфигурация | `/opt/insurance_broker/nginx` |
| Статические файлы | Docker volume: `static_volume` |
| Медиа файлы | Docker volume: `media_volume` |
| База данных | Docker volume: `postgres_data` |

---

## Важные URL

| Что | URL |
|-----|-----|
| Главная страница | https://polis.insflow.ru |
| Админ панель | https://polis.insflow.ru/admin/ |
| API (если есть) | https://polis.insflow.ru/api/ |

---

## Переменные окружения

Основные переменные в `.env.prod`:

```bash
SECRET_KEY=...          # Django secret key
DEBUG=False             # Всегда False в production
ALLOWED_HOSTS=...       # polis.insflow.ru,www.polis.insflow.ru
DB_PASSWORD=...         # Пароль PostgreSQL
EMAIL_HOST_USER=...     # Email для уведомлений
EMAIL_HOST_PASSWORD=... # Пароль email
```

---

## Мониторинг

### Проверка здоровья

```bash
# Статус контейнеров
docker compose -f docker-compose.prod.yml ps

# Использование ресурсов
docker stats

# Свободное место
df -h

# Использование Docker
docker system df
```

### Логи

```bash
# Все логи
docker compose -f docker-compose.prod.yml logs -f

# Последние 100 строк
docker compose -f docker-compose.prod.yml logs --tail=100

# Конкретный сервис
docker compose -f docker-compose.prod.yml logs -f web

# Системные логи
journalctl -u docker -f
```

---

## Обслуживание

### Обновление приложения

```bash
# Через GitHub Actions (автоматически)
git push origin main

# Вручную
ssh root@YOUR_DROPLET_IP
cd /opt/insurance_broker
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
```

### Очистка

```bash
# Удаление неиспользуемых образов
docker image prune -a

# Удаление неиспользуемых volumes
docker volume prune

# Полная очистка (осторожно!)
docker system prune -a --volumes
```

### Перезагрузка сервера

```bash
# Перезагрузка
sudo reboot

# После перезагрузки контейнеры запустятся автоматически
# Проверьте статус
docker compose -f docker-compose.prod.yml ps
```

---

## Контакты и ссылки

**Droplet IP:** `109.68.215.223`
**Домен:** polis.insflow.ru
**SSH:** `ssh root@109.68.215.223`
**Директория:** `/opt/insurance_broker`

### Документация

- [Полное руководство](docs/DEPLOYMENT.md)
- [Руководство по первоначальному развертыванию](docs/INITIAL_DEPLOYMENT_GUIDE.md)
- [Настройка Droplet](docs/DROPLET_SETUP.md)
- [Настройка DNS](docs/DNS_SETUP.md)
- [Бэкапы](docs/BACKUP_RESTORE.md)
- [Мониторинг](docs/MONITORING.md)

---

**Последнее обновление:** 2024-11-25
