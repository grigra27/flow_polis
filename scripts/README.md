# Скрипты Onlinepolis

Сверено с содержимым каталога 2026-11-11.
Скрипты хоста **не обновляются обычным CI-релизом**: workflow доставляет образ,
а не checkout. Изменения библиотек backup/notifications/cron администратор
устанавливает отдельно. [Общее оглавление](../docs/README.md).

## Действующий контур деплоя

| Файл | Назначение |
|---|---|
| [deploy/gate.py](deploy/gate.py) | Разбор фиксированного SSH-протокола |
| [deploy/controller.py](deploy/controller.py) | Проверка политики/архива, upload, activation, health и recovery |
| [deploy/install.sh](deploy/install.sh) | Ручная root-установка отдельного SSH-входа и защищённых файлов |
| [deploy/security.override.yml](deploy/security.override.yml) | UID/GID 10001, cap_drop ALL, no-new-privileges, без setuid entrypoint |

Процедура — в [руководстве по деплою](../docs/DEPLOYMENT.md),
подключение ключа — в [SECURITY.md](../docs/SECURITY.md#установка-ограниченного-доступа).
Запуск Python-файла контроллера вручную не заменяет установленную SSH-границу.

## Резервное копирование и уведомления

| Файл | Назначение |
|---|---|
| [backup-db-telegram.sh](backup-db-telegram.sh) | DB dump/gzip, verify, status, cleanup, Telegram/VK |
| [backup-media-telegram.sh](backup-media-telegram.sh) | Media tar.gz/empty marker, verify, status, cleanup, Telegram/VK |
| [backup-status.sh](backup-status.sh) | Общий контракт этапов и last_status.json; библиотека |
| [backup-retention.sh](backup-retention.sh) | Retention с минимальным числом сохранённых копий; библиотека |
| [telegram-config.sh](telegram-config.sh) | Загрузка env и defaults для bash |
| [telegram-notify.sh](telegram-notify.sh) | Независимая доставка сообщений/файлов Telegram и VK; библиотека |
| [check-notification-config.sh](check-notification-config.sh) | Проверка конфигурации уведомлений с маскированием |
| [setup-backup-cron.sh](setup-backup-cron.sh) | Установка расписания бэкапов с подтверждением |
| [setup-logrotate.sh](setup-logrotate.sh) | Политика ротации persistent Nginx-логов |
| [setup-telegram.sh](setup-telegram.sh) | Интерактивный помощник настройки Telegram; перед запуском сверить его действия и целевой env |

Параметры, проверка и восстановление:
[BACKUP_RESTORE.md](../docs/BACKUP_RESTORE.md).
Доставка и особенности приоритета bash env:
[NOTIFICATIONS_PIPELINE.md](../docs/NOTIFICATIONS_PIPELINE.md).

## База данных

| Файл | Ограничения |
|---|---|
| [restore-local-docker-db.sh](restore-local-docker-db.sh) | Удаляет и заново создаёт фиксированную локальную БД в local_postgres; принимает plain SQL |
| [import_prod_db.sh](import_prod_db.sh) | Фиксированный административный SSH target, production dump и импорт локально; параметры и локальный пароль заданы в скрипте |
| [import-database.sh](import-database.sh) | Старая production-утилита с DROP/CREATE, legacy Compose, запуском web и migrate; не процедура managed release/recovery |

[Единое руководство по БД](../docs/DATABASE_GUIDE.md).

## Другие и устаревшие утилиты

- [view-logs.sh](view-logs.sh) — старый Compose log viewer. Его `--dev` не
  создаёт отсутствующие сервисы (например, Nginx в dev Compose нет).
- [monitor-health.sh](monitor-health.sh) — отдельная Compose/mail-проверка;
  не controller health и не Django system_health_check.
- [deploy.sh](deploy.sh) — **устаревший путь**, не используется текущим workflow:
  собирает на сервере и останавливает весь стек через Compose v1. Не применять
  к managed production; автоматическое восстановление здесь устроено иначе.

Упоминавшихся в старом README `migrate-database.sh`, `init-letsencrypt.sh`,
`check-dns.sh`, `setup-github-secrets.sh`, `verify-github-secrets.sh` и обычных
`backup-db.sh`/`backup-media.sh` в каталоге нет.
История Telegram-туннеля перенесена в
[архив](../docs/archive/telegram-relay-2026-09-24.md).

## Проверки

`scripts/tests/test-*.sh` проверяют backup/retention/status и logrotate.
Они запускаются через bash; подбор и запуск — в
[tests/README.md](../tests/README.md). Production-команды в руководствах
не являются тестами, которые следует выполнять автоматически при правке текста.
