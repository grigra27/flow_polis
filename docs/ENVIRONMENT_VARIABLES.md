# Переменные окружения

Сверено по обращениям к конфигурации в исходном коде 2026-11-11.
Таблица ниже содержит **значения по умолчанию в коде**, а не секреты и не
эффективное окружение production. При проверке реальные `.env` не читались.

## Источники и приоритет

Django читает process environment и локальный `.env` через python-decouple;
переменная процесса имеет приоритет. В обычных тестах `get_runtime_config`
для критичных DB/секретных значений читает только `os.environ`, а не `.env`.
`config.test_settings` задаёт отдельную SQLite и тестовое хранилище.

Production использует **один `.env.prod`**. Compose передаёт его контейнерам
и подставляет `POSTGRES_DB/USER/PASSWORD` в `DB_NAME/USER/PASSWORD` приложений.
`DB_HOST=db`, `DB_PORT=5432` заданы в Compose. Источник interpolation задаётся
контроллером через `--env-file`; для ручных shell-скриптов может понадобиться
экспорт переменных. Смотрите [точную команду Compose](DEPLOYMENT.md).
Старый отдельный `.env.prod.db` текущим production Compose не используется.

При `DEBUG=False` startup проверяет `SECRET_KEY`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `ALLOWED_HOSTS`. DB-поля и ALLOWED_HOSTS должны присутствовать
в окружении процесса. Dev fallback SECRET_KEY не годится для production.
Непустой DB_NAME выбирает PostgreSQL; пустой — SQLite.

## Параметры, которые читает Python

| Переменная | Назначение | Default в коде | Преобразование | Источник |
|---|---|---|---|---|
| `SECRET_KEY` | Подпись Django | `небезопасная dev-заглушка` | `строка` | [config/settings.py:25](../config/settings.py#L25) |
| `DEBUG` | Режим разработки | `True` | `bool` | [config/settings.py:26](../config/settings.py#L26) |
| `ALLOWED_HOSTS` | Разрешённые Host | `localhost,127.0.0.1` | `Csv()` | [config/settings.py:27](../config/settings.py#L27) |
| `SECRET_KEY_FALLBACKS_JSON` | JSON-массив прежних ключей для плановой ротации | `[]` | `строка` | [config/settings.py:43](../config/settings.py#L43) |
| `SENTRY_DSN` | Подключение Sentry | `пусто` | `строка` | [config/settings.py:86](../config/settings.py#L86) |
| `SENTRY_RELEASE` | Метка релиза Sentry | `unknown` | `строка` | [config/settings.py:116](../config/settings.py#L116) |
| `DB_NAME` | Пусто → SQLite, иначе PostgreSQL | `пусто` | `строка` | [config/settings.py:230](../config/settings.py#L230) |
| `DB_USER` | Роль PostgreSQL | `postgres` | `строка` | [config/settings.py:237](../config/settings.py#L237) |
| `DB_PASSWORD` | Пароль роли | `пусто` | `строка` | [config/settings.py:238](../config/settings.py#L238) |
| `DB_HOST` | Адрес PostgreSQL | `localhost` | `строка` | [config/settings.py:239](../config/settings.py#L239) |
| `DB_PORT` | Порт PostgreSQL | `5432` | `строка` | [config/settings.py:240](../config/settings.py#L240) |
| `BACKUP_BASE_DIR` | Базовый каталог поиска копий приложением | `пусто` | `строка` | [config/settings.py:301](../config/settings.py#L301) |
| `BACKUP_DB_DIR` | Явный каталог DB-копий для приложения | `пусто` | `строка` | [config/settings.py:302](../config/settings.py#L302) |
| `BACKUP_MEDIA_DIR` | Явный каталог media-копий для приложения | `пусто` | `строка` | [config/settings.py:303](../config/settings.py#L303) |
| `CELERY_BROKER_URL` | Broker фоновых задач | `redis://localhost:6379/0` | `строка` | [config/settings.py:309](../config/settings.py#L309) |
| `CELERY_RESULT_BACKEND` | Хранилище результатов Celery | `redis://localhost:6379/0` | `строка` | [config/settings.py:310](../config/settings.py#L310) |
| `EMAIL_BACKEND` | Общая Django-почта, отдельно от communications | `django.core.mail.backends.console.EmailBackend` | `строка` | [config/settings.py:322](../config/settings.py#L322) |
| `EMAIL_HOST` | SMTP общей Django-почты | `smtp.gmail.com` | `строка` | [config/settings.py:325](../config/settings.py#L325) |
| `EMAIL_PORT` | SMTP-порт Django | `587` | `int` | [config/settings.py:326](../config/settings.py#L326) |
| `EMAIL_USE_TLS` | STARTTLS общей Django-почты | `True` | `bool` | [config/settings.py:327](../config/settings.py#L327) |
| `EMAIL_HOST_USER` | Django SMTP login | `пусто` | `строка` | [config/settings.py:328](../config/settings.py#L328) |
| `EMAIL_HOST_PASSWORD` | Django SMTP password | `пусто` | `строка` | [config/settings.py:329](../config/settings.py#L329) |
| `COMMUNICATIONS_EMAIL_ENABLED` | Включить бизнес-отправку | `False` | `bool` | [config/settings.py:338](../config/settings.py#L338) |
| `COMMUNICATIONS_DEFAULT_ACCOUNT` | Код основного MailAccount | `billing` | `строка` | [config/settings.py:341](../config/settings.py#L341) |
| `COMMUNICATIONS_SMTP_HOST` | SMTP бизнес-писем | `пусто` | `строка` | [config/settings.py:344](../config/settings.py#L344) |
| `COMMUNICATIONS_SMTP_PORT` | SMTP-порт бизнес-писем | `465` | `int` | [config/settings.py:345](../config/settings.py#L345) |
| `COMMUNICATIONS_SMTP_USE_TLS` | STARTTLS; не включать вместе с SSL | `False` | `bool` | [config/settings.py:346](../config/settings.py#L346) |
| `COMMUNICATIONS_SMTP_USE_SSL` | Implicit TLS; не включать вместе с STARTTLS | `True` | `bool` | [config/settings.py:349](../config/settings.py#L349) |
| `COMMUNICATIONS_SMTP_USERNAME` | SMTP login бизнес-писем | `пусто` | `строка` | [config/settings.py:352](../config/settings.py#L352) |
| `COMMUNICATIONS_SMTP_PASSWORD` | SMTP password бизнес-писем | `пусто` | `строка` | [config/settings.py:353](../config/settings.py#L353) |
| `COMMUNICATIONS_FROM_EMAIL` | Адрес отправителя; fallback на SMTP username | `пусто` | `строка` | [config/settings.py:354](../config/settings.py#L354) |
| `COMMUNICATIONS_FROM_NAME` | Отображаемое имя отправителя | `пусто` | `строка` | [config/settings.py:355](../config/settings.py#L355) |
| `COMMUNICATIONS_MESSAGE_ID_DOMAIN` | Домен Message-ID; fallback из адреса отправителя | `пусто` | `строка` | [config/settings.py:356](../config/settings.py#L356) |
| `COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB` | Максимум МБ на одно вложение | `10` | `int` | [config/settings.py:359](../config/settings.py#L359) |
| `COMMUNICATIONS_SEND_TIMEOUT` | SMTP timeout в секундах | `30` | `int` | [config/settings.py:362](../config/settings.py#L362) |
| `COMMUNICATIONS_BCC_EMAILS` | BCC через запятую/точку с запятой | `пусто` | `строка` | [config/settings.py:369](../config/settings.py#L369) |
| `COMMUNICATIONS_RESTRICT_TO_SUPERUSER` | Ограничить UI отправки суперпользователями | `True` | `bool` | [config/settings.py:372](../config/settings.py#L372) |
| `BILLING_AUTO_UPDATE_TASK_ON_EMAIL_SENT` | Продвигать статус задачи после sent | `True` | `bool` | [config/settings.py:379](../config/settings.py#L379) |
| `SECURE_SSL_REDIRECT` | HTTPS redirect в Django | `True` | `bool` | [config/settings.py:500](../config/settings.py#L500) |
| `SECURE_HSTS_SECONDS` | HSTS Django, секунды | `31536000` | `int` | [config/settings.py:514](../config/settings.py#L514) |
| `FLOW_HANDOFF_ENABLED` | Включить UI перехода из InsFlow | `False` | `bool` | [config/settings.py:556](../config/settings.py#L556) |
| `FLOW_SERVICE_TOKEN` | Общий служебный Bearer-токен InsFlow | `пусто` | `строка` | [config/settings.py:557](../config/settings.py#L557) |
| `FLOW_ZS_BASE_URL` | Сервер источника сводов | `https://zs.insflow.ru` | `строка` | [config/settings.py:558](../config/settings.py#L558) |
| `TELEGRAM_BOT_TOKEN` | Доступ к боту | `пусто` | `строка` | [apps/core/notifications.py:180](../apps/core/notifications.py#L180) |
| `TELEGRAM_CHAT_ID` | Чат получателя | `пусто` | `строка` | [apps/core/notifications.py:181](../apps/core/notifications.py#L181) |
| `TELEGRAM_ENABLED` | Включить Telegram | `False` | `bool` | [apps/core/notifications.py:182](../apps/core/notifications.py#L182) |
| `TELEGRAM_SOCKS5_PROXY` | SOCKS5 host:port для Python и bash | `пусто` | `строка` | [apps/core/notifications.py:183](../apps/core/notifications.py#L183) |
| `VK_COMMUNITY_TOKEN` | Токен сообщества VK | `пусто` | `строка` | [apps/core/notifications.py:361](../apps/core/notifications.py#L361) |
| `VK_USER_ID` | Получатель VK | `пусто` | `строка` | [apps/core/notifications.py:362](../apps/core/notifications.py#L362) |
| `VK_ENABLED` | Включить VK | `False` | `bool` | [apps/core/notifications.py:363](../apps/core/notifications.py#L363) |
| `TELEGRAM_ERROR_RATE_LIMIT` | Общий часовой лимит Python-алертов | `10` | `int` | [apps/core/telegram_handler.py:70](../apps/core/telegram_handler.py#L70) |
| `TELEGRAM_ERROR_MESSAGE_LIMIT` | Бюджет текста ошибки, символы | `500` | `int` | [apps/core/telegram_handler.py:73](../apps/core/telegram_handler.py#L73) |
| `TELEGRAM_EXCEPTION_MESSAGE_LIMIT` | Бюджет исключения, символы | `700` | `int` | [apps/core/telegram_handler.py:76](../apps/core/telegram_handler.py#L76) |
| `TELEGRAM_TRACEBACK_LIMIT` | Бюджет traceback, символы | `2500` | `int` | [apps/core/telegram_handler.py:79](../apps/core/telegram_handler.py#L79) |
| `TELEGRAM_MESSAGE_LIMIT` | Консервативный бюджет Telegram-сообщения | `3900` | `int` | [apps/core/telegram_handler.py:83](../apps/core/telegram_handler.py#L83) |

Часть defaults вычисляется дополнительно: FROM_EMAIL почтового контура может
подставиться из SMTP username; домен Message-ID — из адреса отправителя.
`SECRET_KEY_FALLBACKS_JSON` должен быть JSON-массивом непустых строк.
Почтовые флаги и их эффекты описаны в
[EMAIL_COMMUNICATIONS_SETUP.md](EMAIL_COMMUNICATIONS_SETUP.md), уведомления —
в [NOTIFICATIONS_PIPELINE.md](NOTIFICATIONS_PIPELINE.md).

## Параметры Compose, bash и CI

| Переменная | Назначение / значение по умолчанию | Источник |
|---|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Инициализация PostgreSQL и маппинг в `DB_*`; реальные значения задаёт администратор | [Compose](../docker-compose.prod.yml), [пример](../.env.prod.example) |
| `DEPLOY_SSH_PRIVATE_KEY` | Отдельный приватный ключ CI | [workflow](../.github/workflows/deploy.yml) |
| `DEPLOY_SSH_KNOWN_HOSTS` | Проверенная host key с alias `onlinepolis-production` | [workflow](../.github/workflows/deploy.yml) |
| `DROPLET_HOST` | Адрес сервера | [workflow](../.github/workflows/deploy.yml) |
| `SSH_PORT` | SSH-порт, default `22` | [workflow](../.github/workflows/deploy.yml) |
| `TELEGRAM_UPLOAD_FILES` | Загружать файлы bash-библиотекой, default `true` | [telegram-config.sh](../scripts/telegram-config.sh) |
| `TELEGRAM_MAX_FILE_SIZE` | Лимит bash-загрузки Telegram, default `45` МБ | [telegram-config.sh](../scripts/telegram-config.sh) |

Токены, получатели и SOCKS5 общие с Python-параметрами выше.
Установка доступа CI — в [SECURITY.md](SECURITY.md).

## Параметры бэкапов

Источники — [backup-db-telegram.sh](../scripts/backup-db-telegram.sh),
[backup-media-telegram.sh](../scripts/backup-media-telegram.sh) и
[backup-status.sh](../scripts/backup-status.sh).

| Переменная | Default / смысл |
|---|---|
| `BACKUP_DIR` | `~/insurance_broker_backups/database` для БД, `~/insurance_broker_backups/media` для media |
| `DB_CONTAINER`, `DB_NAME`, `DB_USER` | Для host-скрипта БД: `insurance_broker_db`, `insurance_broker_prod`, `postgres`; это отдельные defaults от Django |
| `MEDIA_VOLUME` | `insurance_broker_media_volume` |
| `MIN_BACKUP_BYTES` | `10240`: нижняя граница размера сжатого DB-дампа |
| `RETENTION_DAYS` | `30` для БД, `28` для media |
| `MIN_RETAINED_BACKUPS` | `5` для БД, `4` для media независимо от возраста |
| `PRINT_ONLY` | `false`; `true` включает просмотр действий cleanup без удаления |
| `DB_REQUIRED_STAGES`, `MEDIA_REQUIRED_STAGES` | Обязательные этапы конкретного типа; fallback на `REQUIRED_STAGES` |
| `REQUIRED_STAGES` | Общий fallback, при отсутствии — `created,verified` |

Процедуры проверки, retention и восстановления остаются в
[BACKUP_RESTORE.md](BACKUP_RESTORE.md).

Bash-библиотека уведомлений сама загружает `.env.prod`, затем `.env`, а затем
применяет defaults. Если существуют оба файла, значения из `.env` загружаются
последними. Внешний shell override одноимённого параметра также может быть
перезаписан файлом: это не тот же приоритет, что у python-decouple.
Не делайте вывод об отключении отправки только по env-префиксу команды.

## Что не настраивается одноимённой env-переменной

В текущем settings.py не читаются одноимённые env-переменные:
`DEFAULT_FROM_EMAIL`, `LOG_LEVEL`, `STATIC_ROOT`, `MEDIA_ROOT`, `STATIC_URL`,
`MEDIA_URL`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
`SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `X_FRAME_OPTIONS` и
другие фиксированные security-параметры. Примеры `.env.example` и
`.env.prod.example` очищены от таких неработающих переключателей.
Эффективное значение фиксированных параметров задаёт Python
или Nginx. Запись в `.env` без обращения из кода ничего не переключает.

`ALLIANCE_BACKUP_MANAGER_ID` и `ALLIANCE_BRANCH_EXTRA_EMAILS` — константы
settings.py, не env. `EMAIL_USE_LOCALTIME=True` также задано в коде.
`EMAIL_*` Django и `COMMUNICATIONS_*` — разные почтовые контуры.

## Применение изменений

Не выводите секреты для проверки. Изменение `.env.prod` требует пересоздания
app-контейнеров: restart не заменяет их environment. Порядок, смена пароля
существующей роли PostgreSQL и временные fallback keys описаны в
[SECRETS_ROTATION.md](SECRETS_ROTATION.md). Обычный CI-релиз не редактирует env.
