# Работа с базой данных

Сверено с [settings.py](../config/settings.py),
[import_prod_db.sh](../scripts/import_prod_db.sh),
[restore-local-docker-db.sh](../scripts/restore-local-docker-db.sh) и
[import-database.sh](../scripts/import-database.sh) 2026-11-11.
Здесь объединены прежние руководства по импорту, переносу и локальному
восстановлению БД. Production-восстановление описано в
[BACKUP_RESTORE.md](BACKUP_RESTORE.md).

## Как выбирается БД

| Режим | Настройка |
|---|---|
| Локальная SQLite | Пустой `DB_NAME`; файл `db.sqlite3` в корне |
| Локальная PostgreSQL | Непустой `DB_NAME` и подходящие `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` |
| Production | `POSTGRES_*` из `.env.prod` маппируются Compose в `DB_*`; адрес `db:5432` |
| Обычный pytest | SQLite из `config.test_settings`, независимо от локального `.env` для критичных DB-настроек |

`docker-compose.yml` для разработки не запускает PostgreSQL. Если приложение
работает на хосте, отдельный контейнер можно опубликовать только на loopback.
Внутри web-контейнера `DB_HOST=localhost` к контейнеру PostgreSQL не ведёт.

## Подготовка локальной PostgreSQL

Для новой локальной копии подберите свободный порт и отдельный том. Пример
использует случайный пароль без вывода значения в терминал:

```bash
set +x
export POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker run -d --name local_postgres   -e POSTGRES_PASSWORD -e POSTGRES_DB=insurance_broker_local   -p 127.0.0.1:5432:5432   -v onlinepolis_local_postgres:/var/lib/postgresql/data postgres:15-alpine
```

Сохраните этот пароль в локальном `.env` защищённым редактором:
`DB_NAME=insurance_broker_local`, `DB_USER=postgres`, `DB_HOST=127.0.0.1`,
`DB_PORT=5432`. Не выводите окружение целиком. Для уже созданного тома
`POSTGRES_PASSWORD` не меняет пароль существующей роли.

## Восстановление локальной копии

Нужен доверенный дамп, полученный через административный доступ или резервное
копирование. Скрипт ниже **удаляет и создаёт заново локальную базу**
`insurance_broker_local` в работающем `local_postgres`.
Он принимает несжатый plain SQL, не custom dump и не `.sql.gz`.

```bash
mkdir -p backups
gzip -t backups/source.sql.gz
gzip -dc backups/source.sql.gz > backups/source.sql
./scripts/restore-local-docker-db.sh backups/source.sql
python manage.py migrate
python manage.py check
```

Если дамп уже несжатый, пропустите распаковку. Скрипт пытается сохранить
старую локальную БД в `backups/current_db_backup_<timestamp>.sql`, затем
проверяет таблицы и записи миграций. Ошибки создания предварительной копии
не блокируют всю процедуру; для ценной локальной БД сделайте и проверьте
отдельную копию заранее. Автоматического отката и `ON_ERROR_STOP` при импорте
в этом скрипте нет: успешный код завершения не заменяет проверку данных.

После импорта убедитесь, что настройки указывают именно на локальную БД,
проверьте миграции, ключевые количества строк и связи. Отключите исходящую
почту, Telegram/VK и Sentry перед запуском копии production-данных.

## Ограничения старых утилит

| Скрипт | Фактическое поведение |
|---|---|
| `import_prod_db.sh` | Административный SSH, фиксированные адрес/имя production-БД, создаёт дамп на сервере, скачивает его, создаёт `local_postgres` и импортирует данные. Локальный пароль задан в скрипте. Это не универсальный безопасный импортёр; перед применением нужен разбор параметров |
| `restore-local-docker-db.sh` | Только локальный контейнер и фиксированное имя БД; удаление/создание БД, plain SQL, попытка предварительной копии |
| `import-database.sh` | Production-ориентированная старая утилита: фиксированное имя БД, legacy Compose v1, удаление БД, затем запуск web и миграций. Несовместима с процедурой обычного релиза через защищённый контроллер |

Ограниченный SSH-ключ CI не даёт shell/SCP-доступ для выгрузки БД.
Не подменяйте им административный доступ. Команда переноса между серверами
должна учитывать формат дампа, версию PostgreSQL, роли, media, секреты и
согласованную остановку записей; одного импорта SQL недостаточно.

## Новая пустая база и миграции

```bash
python manage.py migrate
python manage.py showmigrations --plan
```

Начальные справочники загружаются отдельно, только в новую пустую БД:
`python manage.py loaddata fixtures/initial_data.json`.
Никогда не используйте эту фикстуру для «дополнения» существующих справочников.
CI проверяет пустую БД и повторную загрузку фикстуры на SQLite и PostgreSQL
в готовом production-образе.
