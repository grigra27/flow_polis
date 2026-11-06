# Быстрая справка по развертыванию

## ⚠️ ВАЖНО: Credentials и Сертификаты

После включения B-08 CI доставляет только образ и **не перезаписывает**:
- `.env.prod` - ваши production credentials
- `certbot/` - SSL сертификаты Let's Encrypt

Эти файлы сохраняются между деплоями!

**Ротация и проверка без вывода значений:** [SECRETS_ROTATION.md](SECRETS_ROTATION.md).
**Ограниченный вход CI:** [GITHUB_SECRETS_SETUP.md](GITHUB_SECRETS_SETUP.md).

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
cd /root/insurance_broker

# Подготовить окружение текущей shell, не выводя значения секретов.
set +x
set -a
source .env.prod
set +a

# Только для ручных административных операций после установки B-08.
# Использовать ту же защищённую политику, что и ограниченный CI controller.
compose_admin=(docker compose --compatibility -p insurance_broker --project-directory /root/insurance_broker --env-file /root/insurance_broker/.env.prod -f /etc/onlinepolis-deploy/compose.yml -f /etc/onlinepolis-deploy/security.override.yml)

# Проверить установленный Compose plugin и конфигурацию без вывода переменных.
docker compose version
"${compose_admin[@]}" config --quiet
```

Дальнейшие команды выполняются в этой shell из `/root/insurance_broker`.
Используется Compose plugin версии 2.20 и выше (на production проверен v5.6.0,
2026-11-06). Всегда указывайте `-p insurance_broker`: так сохраняются существующие
сеть, тома и принадлежность контейнеров проекту. Имена образов приложения закреплены
в `docker-compose.prod.yml`. Legacy `docker-compose` v1 оставлен для совместимости
старых read/exec-скриптов; пересоздание контейнеров через него может падать с
`KeyError: ContainerConfig`.

Образ приложения собирается один раз в CI для `linux/amd64`, проходит проверки и
доставляется на сервер как gzip-архив Docker с SHA-256 и manifest исходного коммита.
Сервер проверяет архив и идентичность образа, выполняет `docker load` и назначает
проверенный образ трём существующим тегам приложения. В production Compose нет
`build`-блоков; повторная сборка и загрузка Python-зависимостей на сервере не нужны.

### Изменение серверной конфигурации

CI больше не делает rsync checkout. Изменения Compose, nginx, root scripts и
controller проверяет и устанавливает администратор; при несовпадении source hashes
preflight остановит выкладку. Приложения из образа запускаются с UID/GID10001,
без capabilities и с no-new-privileges. См. [GITHUB_SECRETS_SETUP.md](GITHUB_SECRETS_SETUP.md).

### Управление контейнерами

```bash
# Статус всех контейнеров
"${compose_admin[@]}" ps

# Запуск
"${compose_admin[@]}" up -d

# Остановка
"${compose_admin[@]}" down

# Перезапуск
"${compose_admin[@]}" restart [service]

# Логи
"${compose_admin[@]}" logs -f [service]
```

### Django команды

```bash
# Миграции
"${compose_admin[@]}" exec web python manage.py migrate

# Сбор статики
"${compose_admin[@]}" exec web python manage.py collectstatic --noinput

# Создание суперпользователя
"${compose_admin[@]}" exec web python manage.py createsuperuser

# Django shell
"${compose_admin[@]}" exec web python manage.py shell
```

### SSL сертификат

```bash
# Получение сертификата
./scripts/init-letsencrypt.sh

# Обновление сертификата
"${compose_admin[@]}" run --rm certbot renew
"${compose_admin[@]}" exec nginx nginx -s reload

# Проверка сертификата
"${compose_admin[@]}" run --rm certbot certificates
```

### Бэкапы

```bash
# Бэкап базы данных
"${compose_admin[@]}" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_$(date +%Y%m%d).sql

# Восстановление
"${compose_admin[@]}" exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backup_20240101.sql
```

---

## Проверка работоспособности

### Быстрая проверка

```bash
# Статус контейнеров
"${compose_admin[@]}" ps

# Проверка сайта
curl -I https://polis.insflow.ru

# Проверка HTTP редиректа
curl -I http://polis.insflow.ru
```

### Детальная проверка

```bash
# База данных
"${compose_admin[@]}" exec web python manage.py check --database default

# Celery
"${compose_admin[@]}" exec celery_worker celery -A config inspect ping

# Использование ресурсов
docker stats --no-stream

# Логи
"${compose_admin[@]}" logs --tail=50
```

---

## Troubleshooting

### Контейнер не запускается

```bash
# Проверить логи
"${compose_admin[@]}" logs [service]

# Проверить конфигурацию без вывода секретов
"${compose_admin[@]}" config --quiet
```

Для пересборки и доставки образа повторите workflow: Actions → Deploy to Production
→ Run workflow → main. Не используйте `docker compose build` с production-файлом:
в нём намеренно нет сборки. Workflow проверит CI-артефакт, выполнит подготовку и
переключение, а при ошибке восстановит сохранённые образы и конфигурацию.

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
"${compose_admin[@]}" exec web python manage.py collectstatic --noinput --clear

# Перезапустить Nginx
"${compose_admin[@]}" restart nginx
```

### Ошибки базы данных

```bash
# Проверить статус
"${compose_admin[@]}" ps db

# Проверить логи
"${compose_admin[@]}" logs db

# Проверить соответствие настроек БД, не выводя значения.
"${compose_admin[@]}" exec -T web python - <<'PYCODE'
import os
for runtime, source in (("DB_NAME", "POSTGRES_DB"), ("DB_USER", "POSTGRES_USER"), ("DB_PASSWORD", "POSTGRES_PASSWORD")):
    matches = bool(os.environ.get(runtime)) and os.environ.get(runtime) == os.environ.get(source)
    print(f"{runtime}_matches_{source}={matches}")
PYCODE
```

---

## Важные пути

| Что | Путь |
|-----|------|
| Приложение | `/root/insurance_broker` |
| Логи | `/root/insurance_broker/logs` |
| SSL сертификаты | `/root/insurance_broker/certbot/conf` |
| Nginx конфигурация | `/root/insurance_broker/nginx` |
| Статические файлы | Docker volume: `insurance_broker_static_volume` |
| Медиа файлы | Docker volume: `insurance_broker_media_volume` |
| База данных | Docker volume: `insurance_broker_postgres_data` |

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

# Почтовый контур (отправка писем из карточки задачи billing).
# Полное описание и пошаговая настройка — в docs/EMAIL_COMMUNICATIONS_SETUP.md
COMMUNICATIONS_EMAIL_ENABLED=True
COMMUNICATIONS_SMTP_HOST=smtp.yandex.ru
COMMUNICATIONS_SMTP_PORT=465
COMMUNICATIONS_SMTP_USE_SSL=True
COMMUNICATIONS_SMTP_USERNAME=onlinepolis-billing@yandex.ru
COMMUNICATIONS_SMTP_PASSWORD=...  # пароль приложения Яндекса
COMMUNICATIONS_FROM_EMAIL=onlinepolis-billing@yandex.ru
COMMUNICATIONS_FROM_NAME=ОнлайнПолис
COMMUNICATIONS_RESTRICT_TO_SUPERUSER=True
```

---

## Мониторинг

### Проверка здоровья

```bash
# Статус контейнеров
"${compose_admin[@]}" ps

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
"${compose_admin[@]}" logs -f

# Последние 100 строк
"${compose_admin[@]}" logs --tail=100

# Конкретный сервис
"${compose_admin[@]}" logs -f web

# Системные логи
journalctl -u docker -f
```

---

## Обслуживание

### Обновление приложения

Штатный деплой выполняется через GitHub Actions. Он один раз собирает и проверяет
образ в CI, доставляет его по SSH с проверкой SHA-256, ревизии и идентичности,
сохраняет прежние образы и конфигурацию для восстановления, отдельно выполняет
миграции/статику и проверяет все семь сервисов и HTTPS.

```bash
# Из локального репозитория, после проверок и разрешения на push:
git push origin main

# Повторить pipeline без нового коммита (из локального GitHub CLI):
gh workflow run deploy.yml --ref main --repo grigra27/flow_polis
```

В интерфейсе GitHub: Actions → Deploy to Production → Run workflow → main.
Серверный checkout обновляется через rsync из workflow. Сохранённые образы и
конфигурация находятся в `~/.local/state/onlinepolis-deploy/<run_id>-<run_attempt>/`.
Автоматическое восстановление не откатывает миграции базы данных. Подробности:
[workflow README](../.github/workflows/README.md#recovery).

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
"${compose_admin[@]}" ps
```

---

## Контакты и ссылки

**Droplet IP:** `109.68.215.223`
**Домен:** polis.insflow.ru
**SSH:** `ssh root@109.68.215.223`
**Директория:** `/root/insurance_broker`

### Документация

- [Полное руководство](docs/DEPLOYMENT.md)
- [Руководство по первоначальному развертыванию](docs/INITIAL_DEPLOYMENT_GUIDE.md)
- [Настройка Droplet](docs/DROPLET_SETUP.md)
- [Настройка DNS](docs/DNS_SETUP.md)
- [Бэкапы](docs/BACKUP_RESTORE.md)
- [Мониторинг](docs/MONITORING.md)
- [Почтовый контур: Яндекс.Почта на проде](docs/EMAIL_COMMUNICATIONS_SETUP.md)

---

**Последнее обновление:** 2026-11-06 (Compose plugin и команды действующего production)
