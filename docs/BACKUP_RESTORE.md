# Резервное копирование и восстановление

Сверено с [backup-db-telegram.sh](../scripts/backup-db-telegram.sh),
[backup-media-telegram.sh](../scripts/backup-media-telegram.sh),
[backup-status.sh](../scripts/backup-status.sh),
[backup-retention.sh](../scripts/backup-retention.sh) и
[setup-backup-cron.sh](../scripts/setup-backup-cron.sh) 2026-11-11.
Это описание реализации и процедуры проверки, не новый production restore drill.

## Overview

БД и media копируются отдельно host-скриптами. Их имена сохранили `telegram`,
но доставка работает в Telegram и VK независимо. Репозиторий не создаёт
независимое offsite-хранилище; это [принятый риск](BACKLOG.md).
Успешная доставка файла в мессенджер учитывается как mirror, не как offsite.

| Тип | Формат |
|---|---|
| БД | Plain `pg_dump`, gzip |
| Media | tar.gz из media volume или `.empty` marker |

Каталоги хранения, срок retention и минимальное число копий — в
[справочнике параметров бэкапов](ENVIRONMENT_VARIABLES.md#параметры-бэкапов).

В каталогах также находятся metadata, latest symlink и атомарно записываемый
`last_status.json`. Для пустого media создаётся `.empty` marker; это штатный
пустой снимок, а не tar-архив для распаковки. БД-бэкап не включает media,
сертификаты, `.env.prod`, серверную конфигурацию и права доступа.

## Настройки

Defaults host-скриптов собраны в
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md#параметры-бэкапов).

Допустимые required stages: `created`, `verified`, `offsite`, `notify`.
`mirror` — наблюдаемый результат, не required stage. В текущей реализации
независимый offsite отсутствует, поэтому требование `offsite` завершит прогон
ошибкой. Каналы, лимиты файлов и SOCKS5 — в
[NOTIFICATIONS_PIPELINE.md](NOTIFICATIONS_PIPELINE.md).
Bash загружает конфигурационный env-файл; shell override может быть им
перезаписан. Проверяйте [приоритеты](ENVIRONMENT_VARIABLES.md).

## Ручной запуск и проверка

Команды выполняются администратором на хосте из `/root/insurance_broker`.
Обычный запуск создаёт копию и может отправить сообщения/файлы в мессенджеры.

```bash
./scripts/backup-db-telegram.sh
./scripts/backup-media-telegram.sh
./scripts/backup-db-telegram.sh --list
./scripts/backup-media-telegram.sh --list
./scripts/backup-db-telegram.sh --verify /absolute/path/to/db_backup.sql.gz
./scripts/backup-media-telegram.sh --verify /absolute/path/to/media_backup.tar.gz
```

DB-verify проверяет размер, gzip, заголовок PostgreSQL dump и завершающий marker.
Media-verify проверяет tar и число файлов с учётом metadata. Это проверки
содержимого, **не** полноценное восстановление и не проверка всех связей БД.

`last_status.json` содержит время, тип, файл/размер, `created`, `verified`,
`offsite`, `mirror`, `notify`, список required stages, `result` и `exit`.
Без обязательного notify сбой доставки может оставить backup result успешным,
но с degraded communication. Смотрите весь статус, а не только exit code
или надпись об отправке. `system_health_check --check-backups` читает result
и возраст этого статуса.

## Backup Retention

Cleanup сохраняет минимальное число последних копий независимо от возраста.
Сначала можно посмотреть кандидатов на удаление:

```bash
PRINT_ONLY=true ./scripts/backup-db-telegram.sh --cleanup
PRINT_ONLY=true ./scripts/backup-media-telegram.sh --cleanup
```

Проверка значений retention защищает от некорректных целых параметров.
Не заменяйте cleanup общим удалением каталога или `docker volume prune`.

## Расписание и установка host-изменений

`setup-backup-cron.sh` предлагает установить cron: БД ежедневно в 02:00,
media по понедельникам в 03:00, cleanup обоих типов по понедельникам в 04:00.
Это часы **cron хоста**, не обязательно часовой пояс Django. Реальный crontab
и timezone сервера проверяются отдельно.

Скрипт спрашивает подтверждение, сохраняет прежний crontab и заменяет свои
старые backup entries. Он не устанавливает health-check, logrotate и дайджест.
Обычный CI-релиз **не обновляет host-скрипты или cron**: администратор переносит
проверенные файлы отдельно, сохраняя их библиотечные зависимости.
[Каталог скриптов](../scripts/README.md).

## Database Restore

Сначала выбирайте доверенную копию, проверяйте её и восстанавливайте в отдельную
scratch-БД. Для полного аварийного восстановления нужны также согласованная
media-копия, секреты/конфигурация, сертификаты и совместимый образ приложения.

Пример изолированной проверки DB-дампа; имя контейнера не должно существовать:

```bash
set -o pipefail
set +x
export POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker run -d --name onlinepolis_restore_check   -e POSTGRES_PASSWORD -e POSTGRES_DB=restore_check postgres:15-alpine
```

Дождитесь готовности:
`docker exec onlinepolis_restore_check pg_isready -U postgres -d restore_check`.
Проверьте и импортируйте выбранный plain SQL gzip:

```bash
gzip -t /absolute/path/to/db_backup.sql.gz
gzip -dc /absolute/path/to/db_backup.sql.gz |   docker exec -i onlinepolis_restore_check psql   -X -v ON_ERROR_STOP=1 -U postgres -d restore_check
```

Проверьте миграции, ключевые таблицы/количества строк, FK и отсутствие orphan
records; затем проверьте совместимый app-образ на этой scratch-БД с отключённой
внешней почтой/уведомлениями. Только после этого выбирается процедура возврата
данных на production с остановкой записей и отдельно проверенной копией
текущего состояния. Автоматического отката данных текущий release controller
не выполняет. [Подготовка сервера](DEPLOYMENT.md#первоначальное-развёртывание).

`import-database.sh` — старая destructive-утилита, а не эта процедура:
фиксированная БД, DROP/CREATE без подтверждения, legacy Compose, попытка
предварительной копии с игнорированием части ошибок, затем запуск web и migrate.
Не рассчитывайте на гарантированный backup или автоматический rollback этого
скрипта. [Локальное восстановление и ограничения](DATABASE_GUIDE.md).

## Media Restore

Проверьте список файлов `tar -tzf` и восстановите архив в отдельный новый том.
Убедитесь, что совпадают количество/содержимое файлов и ссылки из выбранной БД.
Не распаковывайте непроверенный архив поверх рабочего media volume.
Для переключения production потребуются права UID/GID `10001:10001` и проверка
авторизованной загрузки документов; публичны только три каталога изображений.

## Recover Single Table

Для частичного восстановления сначала поднимите **полный дамп** в scratch-БД,
затем экспортируйте нужные строки/таблицы с учётом FK и транзакций. Вырезать SQL
через `grep -A` нельзя: это не сохраняет границы COPY, зависимости и порядок.
Решение о переносе в production принимается после сравнения с текущими данными.

## Если копии отсутствуют или устарели

Проверьте логи `backup-db.log`/`backup-media.log`, `last_status.json`, работающий
DB-container, свободное место, имя media volume и crontab. Доступ к каталогу
копий из web — read-only. Удаление старых образов не должно затрагивать
rollback-теги или нужный образ восстановления.

Исторические результаты аудитов и restore drills находятся в
[архиве](archive/README.md), а не являются сегодняшней гарантией восстановления.
