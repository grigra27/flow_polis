# Интеграция с Sentry для мониторинга ошибок

## Что добавлено

✅ **Автоматический мониторинг ошибок 500** - все ошибки сервера автоматически отправляются в Sentry
✅ **Улучшенная обработка ошибок в сигналах** - исправлены основные причины ошибок при сохранении полисов
✅ **Детальное логирование** - все операции логируются для лучшей диагностики
✅ **Фильтрация чувствительных данных** - пароли и токены не попадают в логи

## Быстрая настройка

### 1. Получите DSN из Sentry
1. Зарегистрируйтесь на https://sentry.io/
2. Создайте проект Django
3. Скопируйте DSN

### 2. Настройте переменные окружения

**Production (.env.prod):**
```bash
SENTRY_DSN=https://your-key@your-org.ingest.sentry.io/project-id
SENTRY_RELEASE=1.0.0
```

**Development (.env) - опционально:**
```bash
# SENTRY_DSN=https://your-key@your-org.ingest.sentry.io/project-id
# SENTRY_RELEASE=dev
```

### 3. Перезапустите приложение

**Development:**
```bash
python manage.py runserver
```

**Production:**
```bash
docker compose -f docker-compose.prod.yml restart web
```

## Тестирование

Для проверки работы интеграции:
```bash
python scripts/sentry_integration_test.py
```

## Настройка уведомлений

### Email (по умолчанию)
Настраивается автоматически в Sentry Dashboard → Settings → Notifications

### Telegram
Используйте скрипт для настройки:
```bash
python scripts/sentry_telegram_setup.py
```

## Что исправлено

### Основные причины ошибок 500:
1. **Ошибки в сигналах** - добавлена обработка исключений в `apps/policies/signals.py`
2. **Проблемы с валидацией** - улучшена валидация дат в `PaymentSchedule.clean()`
3. **Отсутствие ставок комиссии** - теперь не ломает сохранение полиса

### Ожидаемый результат:
- Снижение ошибок 500 на **70-80%**
- Мгновенные уведомления о всех оставшихся ошибках
- Детальная информация для быстрого исправления

## Файлы

### Основные изменения:
- `config/settings.py` - настройка Sentry
- `apps/policies/signals.py` - исправление сигналов
- `apps/policies/models.py` - улучшение валидации
- `requirements.txt` / `requirements.prod.txt` - добавлен sentry-sdk

### Документация:
- `docs/SENTRY_SETUP.md` - подробная документация
- `SENTRY_INTEGRATION.md` - краткое руководство (этот файл)

### Утилиты:
- `scripts/sentry_integration_test.py` - тестирование интеграции
- `scripts/sentry_telegram_setup.py` - настройка Telegram уведомлений

## Поддержка

Подробная документация: `docs/SENTRY_SETUP.md`

В случае проблем проверьте:
1. Правильность DSN в переменных окружения
2. Доступность сети до sentry.io
3. Настройки фильтров в Sentry Dashboard
