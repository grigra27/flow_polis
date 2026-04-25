# Pipeline нотификаций: Telegram & VK

Этот документ описывает **как устроена** отправка сообщений и файлов в Telegram и VK в проекте — все каналы, триггеры, лимиты, конфигурация. Это обзорный документ; конкретные improvements собраны в PLAN.md (пункты 8 и follow-up'ы).

Связанные:
- `docs/SECRETS_OVERVIEW.md` — где хранятся `TELEGRAM_BOT_TOKEN`, `VK_COMMUNITY_TOKEN` и пр.
- `docs/ENVIRONMENT_VARIABLES.md` — справочник по env-переменным.

## ⚠️ Главный бизнес-принцип

**Сервер в РФ. Telegram периодически блокируется. VK — резервный канал, должен дойти 100% случаев.**

Из этого следуют **обязательные правила** для любого кода/скрипта, который что-то отправляет:

1. **VK отправляется независимо от результата Telegram.** Не «если TG прошёл, тогда зеркалим в VK», а «отправляем в оба, не ждём успеха одного для другого».
2. **VK отправляется ПЕРВЫМ** там где возможно — Telegram может дать timeout до 10 секунд из-за блокировки, не задерживаемся.
3. **Любая новая точка отправки** должна следовать этим правилам, иначе резервный канал перестаёт быть резервным.
4. В перспективе VK может стать **основным** каналом — закладываем это сейчас.

Что **не** соответствовало правилам и было исправлено 2026-04-25:
- `daily_digest._send_telegram_messages` — VK был внутри `if tg_success`, теперь отправляется всегда.
- `TelegramHandler.emit` — Thread(daemon=True) убивался в management command'ах, ни TG ни VK не отправлялись. Теперь синхронно.
- `TelegramErrorNotifier.notify_*` — та же проблема с Thread, исправлена.

---

## TL;DR

В проекте **два параллельных, не связанных канала** доставки в Telegram/VK:

```
┌─────────────────────────────────────────────────────────────────┐
│  PYTHON-канал                                                    │
│  Внутри Django-контейнера, читает .env через decouple            │
│                                                                  │
│  • TelegramHandler         — logging handler для ERROR+ событий  │
│  • TelegramErrorNotifier   — утилитные методы (system_health и др│
│  • daily_digest command    — суточный отчёт                      │
│  • send_vk_message()       — общая функция VK                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  BASH-канал                                                      │
│  На хосте сервера, читает .env.prod / .env через source          │
│                                                                  │
│  • telegram-config.sh      — загрузка env-переменных             │
│  • telegram-notify.sh      — функции send_telegram_message и др. │
│  • backup-db-telegram.sh   — бэкап БД + уведомление              │
│  • backup-media-telegram.sh — бэкап media                        │
│  • monitor-logs-telegram.sh — tail django.log → ERROR-алерты     │
└─────────────────────────────────────────────────────────────────┘
```

Эти два канала **используют одинаковые токены** (`TELEGRAM_BOT_TOKEN`, `VK_COMMUNITY_TOKEN`) и обычно **тот же chat_id**, но логику обрезания, rate-limit, обработки ошибок реализуют **независимо**. Если изменишь один — второй продолжит работать по-старому.

**Важный нюанс из практики**: сегодняшний alert «🚨 Log Error Detected» про brute-force — это **bash-канал** (`monitor-logs-telegram.sh`). Python-канал шлёт «🚨 Critical Error Detected». То есть **обе системы сейчас работают параллельно** на проде.

---

## Канал 1: Python (внутри Django)

### `apps/core/telegram_handler.py` — `TelegramHandler` (logging handler)

**Триггер**: подключён в `config/settings.py` LOGGING как handler `"telegram"` с `level=ERROR`. Срабатывает на любой `logger.error()` / `logger.critical()` в коде.

**Как работает**:
1. `emit(record)` — основной entry point
2. `_should_send_message()` проверяет:
   - `enabled` + `bot_token` + `chat_id` есть
   - `levelno >= ERROR`
   - **Rate limit**: `len(self.sent_messages) >= max_messages_per_hour` (по умолчанию 10/час)
   - **Группировка**: один и тот же ключ ошибки (`module|exception_type|first_100_chars`) — не чаще раз в 10 мин
3. `_format_message()` — форматирует с emoji-префиксом «🚨 Critical Error Detected», сокращает по лимитам
4. `_send_message_async()` запускается в **отдельном Thread** (daemon thread, fire-and-forget)
5. **В конце метода** `_send_message_async` всегда вызывается `send_vk_message(message)` — то есть VK получает зеркало любого Telegram-алерта

**Лимиты длины** (env-конфигурируемые):
- `TELEGRAM_ERROR_MESSAGE_LIMIT=500` — ужатие сообщения об ошибке
- `TELEGRAM_EXCEPTION_MESSAGE_LIMIT=700` — ужатие текста исключения
- `TELEGRAM_TRACEBACK_LIMIT=2500` — ужатие traceback (с сохранением хвоста, потому что там самое полезное)
- `TELEGRAM_MESSAGE_LIMIT=3900` — финальный лимит на всё сообщение (Telegram hard limit = 4096)

**Состояние**:
- `self.sent_messages: list[datetime]` — для rate-limit, **in-memory**
- `self.message_cache: dict[key, datetime]` — для группировки, **in-memory**
- ⚠️ Под Gunicorn с N воркерами — N независимых счётчиков. Реальный лимит = `N × max_messages_per_hour`.

### `apps/core/telegram_handler.py` — `TelegramErrorNotifier` (статические утилиты)

**Что**: класс с двумя статическими методами:
- `notify_critical_error(title, message, details=None)` — кастомный алерт с заданным заголовком
- `notify_system_health(status, metrics=None)` — health-check уведомление с emoji в зависимости от status

**Как работает**: каждый раз создаёт **новый** `TelegramHandler()` (с заново прочитанным конфигом!), форматирует своё сообщение, запускает Thread на `_send_message_async`. То есть ⚠️ rate-limit/группировка из основного TelegramHandler **НЕ применяются** — это отдельная отправка.

**Кто использует**:
- `apps/core/management/commands/system_health_check.py` — `notify_system_health` после проверки docker/db/disk/memory

### `apps/core/management/commands/daily_digest.py` (~1300 строк)

**Триггер**: management command. Запускается через `python manage.py daily_digest`. Аргументы: `--date YYYY-MM-DD`, `--test` (последние 2 ч), `--no-telegram`, `--no-vk`.

**Должна** запускаться через Celery beat ежедневно (но я не нашёл записи в `django_celery_beat.PeriodicTask` — либо через системный cron, либо вручную).

**Что собирает**:
- `_get_logins_data()` — успешные/неуспешные логины из `LoginAttempt`
- `_get_policies_data()` — изменения полисов из `auditlog.LogEntry` (созданные/обновлённые)
- `_get_payments_data()` — изменения платежей из `LogEntry`
- `_format_message()` — большой текст с эмодзи, статистикой, цифрами, ссылками

**Доставка** (`_send_telegram_messages`):
1. `_split_message_into_parts(max_length=3900)` — режет длинный дайджест на части
2. Для каждой части:
   - `_send_single_telegram_message(message)` — собственная реализация (не TelegramHandler!) с детальной отладкой через `print()`
   - При успехе и `mirror_to_vk=True` — `send_vk_message(message)`
   - **Задержка 1 секунда** между сообщениями, чтобы не превысить Telegram rate-limit
3. Возвращает `{"telegram": N, "vk": M}` — счётчики успешных доставок

**Что особенного**:
- `_send_single_telegram_message` дублирует логику Telegram-отправки из `TelegramHandler`, но **с собственным MAX_MESSAGE_LENGTH = 3900** (захардкожено) и собственной debug-печатью.
- Использует `urllib`, не `requests`, как и `TelegramHandler`.
- При `--no-telegram --no-vk` ничего не делает.

### `apps/core/vk_handler.py` — `send_vk_message(text)`

**Что**: одна функция, которая:
1. Читает `VK_COMMUNITY_TOKEN`, `VK_USER_ID`, `VK_ENABLED` через decouple
2. Если длина > **4096** (`VK_MAX_MESSAGE_LENGTH` захардкожено) — обрезает в конце
3. Генерирует random `random_id` (защита от ретраев на стороне VK)
4. POST на `https://api.vk.com/method/messages.send` (API version `5.199`)
5. Обрабатывает HTTPError и общие Exception, логирует

**Возвращает**: `True` / `False`.

### `apps/core/management/commands/test_telegram_errors.py`

**Что**: ручной тест Telegram-уведомлений. Флаги: `--test-error`, `--test-critical`, `--test-exception`. Использует `TelegramErrorNotifier`.

---

## Канал 2: Bash (на хосте сервера)

### `scripts/telegram-config.sh`

**Что**: загружает env через `source .env.prod`, потом `source .env` (если есть). Экспортирует `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED`, `TELEGRAM_UPLOAD_FILES`, `TELEGRAM_MAX_FILE_SIZE`, `TELEGRAM_API_URL`, `VK_ENABLED`, `VK_COMMUNITY_TOKEN`, `VK_USER_ID`. Подключается в начале каждого bash-скрипта.

**Дефолты**: `TELEGRAM_ENABLED=false`, `TELEGRAM_UPLOAD_FILES=true`, `TELEGRAM_MAX_FILE_SIZE=45` (Telegram hard limit для ботов = 50 МБ), `VK_ENABLED=false`.

### `scripts/telegram-notify.sh` (~700 строк)

**Что**: библиотека функций для bash-скриптов. Сорсится в начале backup/monitor скриптов.

**Функции отправки**:
- `send_telegram_message_only(text)` — `curl -4` (форс IPv4 — обход IPv6-багов в Docker), retry 2, timeout 15+60s
- `send_telegram_file_only(path, caption)` — sendDocument, проверка размера, **автокомпрессия gzip** если > `TELEGRAM_MAX_FILE_SIZE`
- `send_vk_mirror_message(text)` — VK messages.send через curl
- `send_vk_file(path, caption)` — **4-шаговая загрузка**: docs.getMessagesUploadServer → upload bytes → docs.save → messages.send (с attachment)
- `send_telegram_message(text)` — параллельная отправка в TG + VK через `&` и `wait`. **Возвращает 0 если хотя бы один канал успел.**
- `send_telegram_file(path, caption)` — то же но для файлов

**Wrapper-функции** для backup-скриптов:
- `notify_backup_start(type)` — «🔄 Backup Started»
- `notify_backup_success(type, file, size, duration)` — «✅ Backup Completed Successfully» + **загрузка файла**
- `notify_backup_error(type, error)` — «❌ Backup Failed»
- `notify_cleanup_result(type, count, retention)` — «🧹 Cleanup Completed»

**JSON-парсинг**: для VK file upload используется `python3 -c '...'` чтобы вытащить поля из JSON ответа (нет jq).

### `scripts/backup-db-telegram.sh`

**Триггер**: cron на сервере (см. `scripts/setup-backup-cron.sh`).

**Что делает**:
1. `notify_backup_start("Database Backup")` — TG + VK
2. `pg_dump` через docker exec
3. `gzip` сжатие
4. `notify_backup_success("Database Backup", file, size, duration)` — TG + VK + **загрузка файла в TG и VK параллельно**
5. `cleanup_old_backups()` (старше `RETENTION_DAYS=7`)
6. `notify_cleanup_result("Database Backup", count, retention)`

При любой ошибке — `notify_backup_error(...)`.

### `scripts/backup-media-telegram.sh`

То же самое, но для media volume.

### `scripts/monitor-logs-telegram.sh`

**Триггер**: запускается как daemon (`--daemon`) или разово (`--once`) через cron.

**Что делает**:
1. Хранит позицию чтения логов в `logs/.monitor_state` — продолжает с последнего места
2. Каждые `CHECK_INTERVAL` секунд (по умолчанию 60) читает новые строки `logs/django.log` и `logs/security.log`
3. Если строка содержит `ERROR` или `CRITICAL` — вызывает `send_error_notification`:
   - Свой собственный rate-limit `MAX_ERRORS_PER_HOUR=10` (через тот же state file)
   - Формирует сообщение «🚨 Log Error Detected» — отличается от Python «🚨 Critical Error Detected»
   - Отправляет через `send_telegram_message` (TG+VK параллельно)

**Это причина, по которой ты получаешь два разных вида алертов** — один из Python (когда Django вызывает `logger.error`), и один из bash (когда тот же логер записал в файл и monitor его подобрал). На текущем проде вероятно работают оба — это и есть **дублирование**.

### `scripts/setup-telegram.sh`, `scripts/setup-error-monitoring.sh`

Однократные setup-скрипты для первой настройки. Запрашивают токены, валидируют, прописывают в `.env.prod`.

### `scripts/monitor-health.sh`

**Не использует Telegram/VK** — это про email alerting (флаг `--alert-email`). Упоминаю чтобы не было путаницы: «health» в названии не значит «шлёт в Telegram». В Python `system_health_check` шлёт.

---

## Конфигурация: где какая переменная читается

| Переменная | Python (decouple) | Bash (env) | Default |
|------------|-------------------|------------|---------|
| `TELEGRAM_BOT_TOKEN` | ✓ | ✓ | пусто |
| `TELEGRAM_CHAT_ID` | ✓ | ✓ | пусто |
| `TELEGRAM_ENABLED` | ✓ | ✓ | `false` |
| `TELEGRAM_UPLOAD_FILES` | ✗ | ✓ | `true` |
| `TELEGRAM_MAX_FILE_SIZE` | ✗ | ✓ | `45` |
| `TELEGRAM_ERROR_RATE_LIMIT` | ✓ | ✗ | `10` |
| `TELEGRAM_ERROR_MESSAGE_LIMIT` | ✓ | ✗ | `500` |
| `TELEGRAM_EXCEPTION_MESSAGE_LIMIT` | ✓ | ✗ | `700` |
| `TELEGRAM_TRACEBACK_LIMIT` | ✓ | ✗ | `2500` |
| `TELEGRAM_MESSAGE_LIMIT` | ✓ | ✗ | `3900` |
| `MAX_ERRORS_PER_HOUR` (bash monitor) | ✗ | ✓ | `10` |
| `VK_COMMUNITY_TOKEN` | ✓ | ✓ | пусто |
| `VK_USER_ID` | ✓ | ✓ | пусто |
| `VK_ENABLED` | ✓ | ✓ | `false` |

Обрати внимание:
- **Python-rate-limit и bash-rate-limit идут под одним именем** в коде, но **через разные переменные**. Их нельзя поменять одной правкой.
- **`TELEGRAM_UPLOAD_FILES`** — только в bash. Python нигде не загружает файлы.
- **`TELEGRAM_*_LIMIT`** — только в Python. В bash нет понятия лимита длины сообщения (полагается на вызывающего).

---

## Дублирования и расхождения

### 1. Две независимые реализации отправки в Telegram

| Аспект | Python (TelegramHandler) | Python (daily_digest) | Bash (telegram-notify.sh) |
|--------|--------------------------|------------------------|---------------------------|
| HTTP клиент | urllib | urllib | curl |
| Retry | нет | нет | `--retry 2-3` |
| Force IPv4 | нет | нет | `-4` |
| Обрезание | `_trim_with_middle_ellipsis` | `_truncate_message` | нет (полагается на caller) |
| Rate limit | in-memory list | нет | state file |
| Группировка | in-memory dict | нет | нет |
| Параллельная VK-отправка | нет (последовательно) | нет (последовательно) | да (через `&` + `wait`) |

### 2. Лимит длины сообщения — три места

- `apps/core/telegram_handler.py:52` — `TELEGRAM_MESSAGE_LIMIT=3900` (env-настраиваемый)
- `apps/core/management/commands/daily_digest.py:1114, 1261` — `3900` захардкожено в двух местах
- `apps/core/vk_handler.py:19` — `VK_MAX_MESSAGE_LENGTH=4096` захардкожено
- В bash — лимита нет

### 3. Rate-limit «10 в час» — два независимых счётчика

- `TelegramHandler.sent_messages` (Python, in-memory)
- `monitor-logs-telegram.sh:.monitor_state` (Bash, file)

Они не координируются. Если Python `logger.error` срабатывает 10 раз и упёрся в свой лимит — bash-monitor может прислать ещё 10 алертов про те же ошибки (они уже в файле логов).

### 4. Два разных формата сообщения для одной и той же ошибки

Если в коде `logger.error("X")`:
- Python TelegramHandler сразу отправит «🚨 Critical Error Detected\n📊 Level: ERROR\n…»
- Bash monitor через ~60 секунд прочитает строку и отправит «🚨 Log Error Detected\n📁 Log File: django.log\n…»

Прод видит **оба сообщения**.

### 5. VK-зеркалирование — три разные стратегии

- `TelegramHandler._send_message_async` — после Telegram **всегда** зеркалит в VK
- `daily_digest._send_telegram_messages(mirror_to_vk=True)` — управляется флагом
- Bash `send_telegram_message` — параллельно в обе системы

### 6. Файлы — только bash

VK file upload реализован только в bash (`send_vk_file`, 4 шага). Python вообще не умеет грузить файлы куда-либо. Если Python захочет послать файл (например, экспорт Excel в TG) — придётся писать с нуля.

---

## Дыры и риски

### 1. ~~**Threading в TelegramHandler** = unbounded fan-out~~ — ИСПРАВЛЕНО 2026-04-25 (Thread удалён, отправка синхронная)

Раньше `emit()` создавал `Thread(daemon=True)` на каждое логированное событие. Кроме fan-out риска, daemon thread killed в management commands вообще терял сообщения. Теперь — синхронно. Под нагрузкой rate-limit (10/час) защищает от блокировки логгера.

### 2. **Rate-limit per-process under Gunicorn**

Если Gunicorn запускает 4 воркера, у каждого свой `self.sent_messages`. Реальный потолок = 4 × 10 = 40/час, не 10. После рестарта счётчик обнуляется → возможность спама в первый час после деплоя.

### 3. **Telegram API rate-limit 429 не обрабатывается**

Telegram возвращает HTTP 429 + `retry_after` если бот превысил их лимиты (~30 сообщений/сек на чат). Сейчас:
- Python: молча залогируется в print (не в Django logger!), сообщение потеряно
- Bash: `curl --retry 2` повторит сразу, скорее всего опять 429, опять fail

### 4. **TELEGRAM_BOT_TOKEN утечка через ошибочный логгер**

В `telegram_handler.py` URL формируется как `https://api.telegram.org/bot{TOKEN}` (строка 59). Если эта строка попадёт в исключение и Django залогирует — **токен уйдёт в логи** (а оттуда в TG-канал того же бота). Сейчас вроде нет таких мест, но риск есть.

### ~~Дублирование VK не гарантировалось~~ — ИСПРАВЛЕНО 2026-04-25

Раньше было два бага, ломавших главный принцип «VK = 100%-резервный канал»:
- `daily_digest._send_telegram_messages` — VK отправлялся **только** при успехе TG (внутри `if tg_success`). Когда TG падал, дайджест не доходил никуда.
- `TelegramHandler.emit` создавал `Thread(daemon=True)` — в management command'ах thread убивался до HTTP-запроса. Ни TG ни VK не отправлялись.
- `TelegramErrorNotifier.notify_critical_error / notify_system_health` — та же daemon-thread проблема.

Сейчас (после правки): VK отправляется всегда, синхронно, **первым** (раньше TG, чтобы не задерживаться на 10s timeout). См. apps/core/telegram_handler.py и apps/core/management/commands/daily_digest.py:_send_telegram_messages.

### 6. **VK random_id уникален «в рамках одного запуска»**

`vk_handler.py:53` — `random.randint(1, 2**31 - 1)`. Если процесс отправит два сообщения подряд за миллисекунды — random может совпасть → VK дедупит, второе сообщение **молча потеряется**. На практике маловероятно, но не нулевой риск. Лучше использовать монотонный счётчик + время.

### 6. **VK 4096 — обрезка в конце**

`vk_handler.py:49` — `text[:VK_MAX_MESSAGE_LENGTH]`. Это режет **конец** сообщения. Для traceback'ов важнее конец (там тип исключения). VK получит начало, без главной информации. В Python TelegramHandler есть умное обрезание `_trim_with_middle_ellipsis` — VK его не использует.

### 7. **Конфигурация через два файла**

Если `.env` (Python) и `.env.prod` (bash) разъехались по `TELEGRAM_BOT_TOKEN` — Python и bash будут писать в разные чаты или один из них замолчит. Никакой проверки нет.

### 8. **Дайджест не имеет fallback**

В `daily_digest._send_telegram_messages` если Telegram упал — VK тоже не отправится (логика mirror только при success TG). Плюс нет retry если оба упали.

### 9. **`monitor-logs-telegram.sh` зависит от файла лога**

Если `logs/django.log` не существует или ротируется чем-то нестандартным — monitor либо ничего не делает, либо ловит «file rotated, starting from beginning» и присылает огромный пакет старых ошибок.

### 10. **`TelegramErrorNotifier` создаёт новый handler на каждый вызов**

`notify_critical_error()` и `notify_system_health()` делают `handler = TelegramHandler()` каждый раз — это **новый rate-limit-счётчик**. Поэтому health-check может слать неограниченно (свой счётчик пуст). Хорошо это или плохо — зависит от точки зрения.

---

## Куда двигаться

Список follow-up задач, которые я сформировал по итогам аудита, добавлен в `PLAN.md`:

- **#8** (был раньше): rate-limit в Redis, чтобы Python и bash считали один счётчик; threading на Celery
- **#11.1**: убрать дублирование Python ↔ bash для error-мониторинга. Один из вариантов — выпилить `monitor-logs-telegram.sh` целиком, оставить только Python TelegramHandler. Тогда ошибки логирования идут одним путём.
- **#11.2**: единая утилита `apps.core.notifications` — обертка над Telegram + VK с единой обрезкой, ретраями, обработкой 429
- **#11.3**: VK file upload в Python (если когда-то захотим слать Excel-экспорты)
- **#11.4**: проверка консистентности `.env` и `.env.prod` (скрипт sanity-check на сервере)
- **#11.5**: 429-aware retry с уважением `retry_after`

См. PLAN.md, секция «11. Полный аудит pipeline...» — там это разнесено по приоритетам.
