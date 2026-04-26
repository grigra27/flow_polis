# Telegram и VK уведомления

Уведомления отправляются через единый Python-pipeline (`apps.core.notifications`).
Архитектура описана в [NOTIFICATIONS_PIPELINE.md](./NOTIFICATIONS_PIPELINE.md).

---

## Настройка бота

### Шаг 1: Создать бота

1. Найти `@BotFather` в Telegram
2. `/newbot` → задать имя и username
3. Сохранить **Bot Token** (формат `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Шаг 2: Получить Chat ID

1. Создать приватный канал, добавить бота как администратора
2. Отправить любое сообщение в канал
3. Открыть в браузере: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Найти `"chat":{"id":-1001234567890}` — это и есть Chat ID

### Шаг 3: Прописать в .env.prod

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_ENABLED=true
TELEGRAM_ERROR_RATE_LIMIT=10
```

### Шаг 4: Перезапустить контейнеры

```bash
cd ~/insurance_broker
set -a; source .env.prod; set +a
docker-compose -f docker-compose.prod.yml up -d
```

### Проверка

```bash
# Проверить что Django видит переменные и они совпадают с .env.prod
./scripts/check-notification-config.sh

# Тест отправки через management command
docker-compose -f docker-compose.prod.yml exec web python manage.py test_telegram_errors --test-custom
```

---

## Мониторинг ошибок

Все ERROR и CRITICAL из Django logging автоматически летят в Telegram (и дублируются в VK).

**Настройка уже сделана** в `config/settings.py` — `TelegramHandler` подключён к логгеру `telegram`. Менять ничего не нужно.

### Rate limiting

Управляется через Redis. Переменная `TELEGRAM_ERROR_RATE_LIMIT` задаёт максимум уведомлений в час (по умолчанию 10).

```bash
# В .env.prod
TELEGRAM_ERROR_RATE_LIMIT=10
```

### Тест отправки ошибок

```bash
docker-compose -f docker-compose.prod.yml exec web python manage.py test_telegram_errors --test-error
docker-compose -f docker-compose.prod.yml exec web python manage.py test_telegram_errors --test-exception
```

### Проверка системы

```bash
docker-compose -f docker-compose.prod.yml exec web python manage.py system_health_check --check-all
```

### Пример уведомления об ошибке

```
🚨 Critical Error Detected

🕐 Time: 2024-01-15 14:30:25 UTC
📊 Level: ERROR
📁 Module: views

👤 User: manager_ivan (ID: 5)
🌐 URL: /policies/create/
📱 Method: POST

❗ Error: Database connection lost
```

---

## Ежедневный дайджест

**Расписание:** каждый день в 6:00 МСК (3:00 UTC).

Cron на сервере:
```bash
0 3 * * * cd /root/insurance_broker && docker-compose -f docker-compose.prod.yml exec -T web python manage.py daily_digest >> /root/insurance_broker/logs/daily-digest.log 2>&1
```

### Что включает дайджест

- **Сводная статистика:** количество созданных/изменённых полисов, суммы премий и КВ
- **Активность пользователей:** кто и когда входил
- **Детали по платежам:** оплаченные, просроченные, завтрашние
- **Детали по полисам:** созданные и изменённые, с прямыми ссылками на `polis.insflow.ru`

### Ручной запуск

```bash
# Дайджест за вчера
docker-compose -f docker-compose.prod.yml exec web python manage.py daily_digest

# За конкретную дату
docker-compose -f docker-compose.prod.yml exec web python manage.py daily_digest --date 2024-12-22

# Тестовый (последние 2 часа)
docker-compose -f docker-compose.prod.yml exec web python manage.py daily_digest --test
```

### Длинные сообщения

Telegram ограничивает сообщения 4096 символами. При превышении дайджест автоматически разбивается на части с нумерацией (Часть 1/2, 2/2 и т.д.).

---

## Устранение неполадок

**Уведомления не приходят:**
```bash
# Проверить конфиг
./scripts/check-notification-config.sh

# Посмотреть логи Django
docker-compose -f docker-compose.prod.yml logs web | grep -i telegram
```

**Дайджест не приходит:**
```bash
# Проверить cron
crontab -l | grep daily_digest

# Посмотреть логи
tail -f logs/daily-digest.log

# Запустить вручную
docker-compose -f docker-compose.prod.yml exec web python manage.py daily_digest --test
```

**Слишком много уведомлений об ошибках:**
Уменьшить `TELEGRAM_ERROR_RATE_LIMIT` в `.env.prod`, перезапустить контейнеры.

**Расхождение токенов после ротации:**
```bash
./scripts/check-notification-config.sh
# Если есть расхождение — перезапустить контейнеры:
set -a; source .env.prod; set +a
docker-compose -f docker-compose.prod.yml up -d
```
