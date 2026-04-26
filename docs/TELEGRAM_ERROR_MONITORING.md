# Telegram Error Monitoring Setup

Система мониторинга критических ошибок с уведомлениями в Telegram для Django приложения.

## 🎯 Возможности

- **Автоматические уведомления** о критических ошибках Django
- **Rate limiting** - защита от спама уведомлений
- **Группировка ошибок** - одинаковые ошибки не дублируются
- **Асинхронная отправка** - не блокирует основное приложение
- **Мониторинг логов** - отслеживание файлов логов в реальном времени
- **Проверка системы** - мониторинг состояния сервера
- **Единый канал** - все уведомления в том же канале что и бэкапы

## 📋 Предварительные требования

1. Настроенный Telegram бот (см. `TELEGRAM_SETUP_GUIDE.md`)
2. Django приложение с настроенным логированием
3. Docker контейнер пересобран с новыми зависимостями

## ⚙️ Установка

### 1. Пересборка Docker контейнера

```bash
# Пересоберите контейнер для установки новых зависимостей
docker-compose -f docker-compose.prod.yml build web

# Перезапустите сервисы
docker-compose -f docker-compose.prod.yml up -d
```

### 2. Настройка переменных окружения

### 2. Настройка переменных окружения

Добавьте в `.env.prod` файл:

```bash
# Telegram Error Monitoring
TELEGRAM_ERROR_RATE_LIMIT=10  # Максимум уведомлений в час
```

Остальные настройки Telegram уже должны быть настроены для бэкапов.

### 3. Проверка настроек Django

Убедитесь что в `config/settings.py` добавлен Telegram handler в LOGGING конфигурацию (уже сделано автоматически).

## 🧪 Тестирование

### Тест Django logging handler

```bash
# Тест обычной ошибки
python manage.py test_telegram_errors --test-error

# Тест критической ошибки
python manage.py test_telegram_errors --test-critical

# Тест исключения с traceback
python manage.py test_telegram_errors --test-exception

# Тест кастомного уведомления
python manage.py test_telegram_errors --test-custom
```

### Тест мониторинга системы

```bash
# Проверка состояния системы
python manage.py system_health_check --check-all

# Проверка с отправкой в Telegram
python manage.py system_health_check --check-all --notify-telegram

# Проверка только базы данных
python manage.py system_health_check --check-db --notify-telegram
```

### Тест мониторинга логов

```bash
# Тест функциональности
./scripts/monitor-logs-telegram.sh --test

# Проверка статуса
./scripts/monitor-logs-telegram.sh --status

# Разовая проверка логов
./scripts/monitor-logs-telegram.sh --once
```

## 🚀 Запуск мониторинга

### Автоматический мониторинг ошибок Django

Мониторинг ошибок Django работает автоматически через logging handler. Все ERROR и CRITICAL сообщения будут отправляться в Telegram.

### Мониторинг логов в реальном времени

```bash
# Запуск как демон (непрерывный мониторинг)
./scripts/monitor-logs-telegram.sh --daemon

# Или добавьте в systemd service
sudo tee /etc/systemd/system/telegram-log-monitor.service > /dev/null <<EOF
[Unit]
Description=Telegram Log Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/insurance_broker
ExecStart=/root/insurance_broker/scripts/monitor-logs-telegram.sh --daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable telegram-log-monitor
sudo systemctl start telegram-log-monitor
```

### Регулярная проверка системы

Добавьте в crontab:

```bash
# Проверка системы каждые 30 минут
*/30 * * * * cd /root/insurance_broker && python manage.py system_health_check --check-all --notify-telegram >> /root/insurance_broker/logs/health-check.log 2>&1

# Или только при проблемах (проверка каждые 5 минут, уведомление только при ошибках)
*/5 * * * * cd /root/insurance_broker && python manage.py system_health_check --check-all --notify-telegram 2>/dev/null || echo "Health check failed" >> /root/insurance_broker/logs/health-check.log
```

## 📱 Примеры уведомлений

### Критическая ошибка Django

```
🚨 Critical Error Detected

🕐 Time: 2024-01-15 14:30:25 UTC
📊 Level: ERROR
📁 Module: views
🖥 Server: your-server

👤 User: john_doe (ID: 123)
🌐 URL: /api/reports/generate
📱 Method: POST

❗ Error:
Database connection lost during report generation

📋 Traceback:
File "/app/views.py", line 45, in generate_report
  result = db.execute(query)
DatabaseError: connection lost
```

### Проверка системы

```
⚠️ System Health Check

🕐 Time: 2024-01-15 14:30:00 UTC
📊 Status: WARNING
🖥 Server: your-server

📈 Metrics:
• Database: healthy - Database connection OK
• Disk: warning - Disk usage high: 85.2% used
• Memory: healthy - Memory usage normal: 65.1% used
```

### Мониторинг логов

```
🚨 Log Error Detected

📁 Log File: django.log
📊 Level: ERROR
🕐 Detected: 2024-01-15 14:30:15 UTC
📝 Log Time: 2024-01-15 14:30:10
🖥 Server: your-server

❗ Error Message:
IntegrityError: UNIQUE constraint failed: users_user.email

📋 Rate Limit: 3/10 per hour
```

## ⚙️ Настройки

### Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `TELEGRAM_ERROR_RATE_LIMIT` | Макс. уведомлений об ошибках в час | 10 |
| `CHECK_INTERVAL` | Интервал проверки логов (сек) | 60 |
| `MAX_ERRORS_PER_HOUR` | Макс. уведомлений от монитора логов | 10 |

### Настройка rate limiting

Rate limiting работает на двух уровнях:

1. **Django Handler** - не более N ошибок в час от приложения
2. **Log Monitor** - не более N ошибок в час от мониторинга файлов

### Группировка ошибок

Одинаковые ошибки группируются по:
- Модулю где произошла ошибка
- Типу исключения
- Первой строке сообщения об ошибке

Повторные ошибки не отправляются чаще чем раз в 10 минут.

## 🔧 Кастомные уведомления

### Из Django кода

```python
from apps.core.telegram_handler import TelegramErrorNotifier

# Отправка критической ошибки
TelegramErrorNotifier.notify_critical_error(
    title='Payment Processing Error',
    message='Failed to process payment for order #12345',
    details={'order_id': 12345, 'amount': 150.00, 'error_code': 'CARD_DECLINED'}
)

# Отправка статуса системы
TelegramErrorNotifier.notify_system_health(
    status='warning',
    metrics={
        'active_users': 150,
        'queue_size': 25,
        'response_time': '250ms'
    }
)
```

### Из bash скриптов

```bash
# Загрузите функции Telegram
source scripts/telegram-notify.sh

# Отправьте сообщение об ошибке
send_telegram_message "🚨 <b>Backup Script Error</b>

❗ Failed to create database backup
🕐 Time: $(date)
🖥 Server: $(hostname)"
```

## 🚨 Устранение неполадок

### Ошибки не отправляются

1. Проверьте настройки Telegram:
   ```bash
   ./scripts/telegram-notify.sh test
   ```

2. Проверьте переменные окружения:
   ```bash
   python -c "from decouple import config; print('TELEGRAM_ENABLED:', config('TELEGRAM_ENABLED', default=False))"
   ```

3. Проверьте логи Django:
   ```bash
   tail -f logs/django.log | grep -i telegram
   ```

### Слишком много уведомлений

1. Увеличьте rate limit:
   ```bash
   # В .env.prod
   TELEGRAM_ERROR_RATE_LIMIT=5  # Уменьшите количество
   ```

2. Проверьте группировку ошибок в коде

3. Исправьте источник ошибок в приложении

### Мониторинг логов не работает

1. Проверьте права доступа к файлам логов:
   ```bash
   ls -la logs/
   ```

2. Проверьте статус мониторинга:
   ```bash
   ./scripts/monitor-logs-telegram.sh --status
   ```

3. Проверьте systemd service (если используется):
   ```bash
   sudo systemctl status telegram-log-monitor
   sudo journalctl -u telegram-log-monitor -f
   ```

## 🔒 Безопасность

1. **Фильтрация данных** - используются существующие фильтры Django для удаления чувствительных данных
2. **Rate limiting** - защита от спама уведомлений
3. **Асинхронность** - ошибки в Telegram не влияют на основное приложение
4. **Ограничение размера** - сообщения и traceback ограничены по размеру

## 📊 Мониторинг производительности

Система мониторинга имеет минимальное влияние на производительность:

- **Django Handler**: ~1-2ms на ошибку (асинхронно)
- **Log Monitor**: ~1-5% CPU при активном мониторинге
- **Health Check**: ~100-200ms на проверку

Rate limiting гарантирует что даже при большом количестве ошибок нагрузка остается минимальной.
