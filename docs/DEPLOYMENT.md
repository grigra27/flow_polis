# Деплой и инфраструктура

Сверено с [workflow](../.github/workflows/deploy.yml),
[controller.py](../scripts/deploy/controller.py),
[gate.py](../scripts/deploy/gate.py), [install.sh](../scripts/deploy/install.sh),
[Compose](../docker-compose.prod.yml) и
[security override](../scripts/deploy/security.override.yml) 2026-11-11.
Здесь объединены релизы, подготовка сервера и справочник production Compose.
Состояние конкретного сервера проверяется отдельно.

## Обычный релиз

`Deploy to Production` запускается при push в `main` и через `workflow_dispatch`.
`concurrency: onlinepolis-production` не отменяет уже идущий запуск.
Для релиза с окном обслуживания ручной запуск с `activate=false` выполняет
проверки и сохраняет verified image artifact, но не запускает deploy/rollback.
Это позволяет подготовить и проверить образ до остановки записи. Администратор
затем передаёт тот же artifact контроллеру командами `upload`, `activate`, `health`,
сверяя SHA, digest и защищённую конфигурацию по обычной процедуре.

1. **validate** проверяет Compose с примером окружения и обязательные файлы.
2. **test** запускает весь pytest на Python 3.12 с `config.test_settings`.
3. **build** один раз собирает `linux/amd64` с revision commit SHA. Готовый
   образ проверяется запуском Python, Redis broker round trip и bootstrap
   PostgreSQL 15: миграции, начальные справочники, `check --deploy`, отсутствие
   новых миграций и collectstatic.
4. CI сохраняет `image.tar.gz`, checksum и manifest в immutable artifact
   на **два дня**. Config digest связывает архив с проверенными слоями
   и runtime configuration образа.
5. **deploy** скачивает точный artifact ID, проверяет digest и подключается
   к `onlinepolis-deploy` с закреплённым host key.
6. **status** проверяет протокол и хеши защищённой конфигурации.
7. **upload** принимает ограниченный поток архива. Контроллер проверяет размер,
   checksum, платформу, revision, config/layers и единственный разрешённый tag;
   перед Docker loader архив перепаковывается.
8. **activate** сохраняет прежние образы, загружает новый и назначает три
   app-тега. Одноразовые контейнеры выполняют `migrate --noinput` и
   `collectstatic --noinput`, затем пересоздаются три приложения и Nginx.
9. **health** сверяет native image IDs, runtime-политику приложений,
   состояние семи сервисов и HTTPS-страницу входа.

CI передаёт готовый образ через фиксированный SSH-протокол; сборки на сервере,
rsync/SCP checkout и произвольного remote bash в этом процессе нет.
`notify` печатает итог в лог Actions; Telegram/email из этого job не отправляются.

### Первый релиз истории ставок КВ

Миграции `insurers.0016`, `policies.0026`, `insurers.0017` требуют окна
обслуживания: до запуска `migrate` остановить запись старым web, worker и beat,
дождаться завершения выполняющихся записей и сделать резервную копию БД.
Обычный `activate` сам приложения перед миграциями не останавливает — подготовка
этого первого релиза выполняется отдельно по административному доступу.

Причина: старая версия ожидает одну ставку на компанию и вид, а новые строки
полисов между переносом условий и переключением приложения не получили бы
закреплённую базовую ставку. Запись возобновляется только на новом образе.
После переключения выполнить `audit_commission_rates` и сверить количество
полисов/платежей, прежние ссылки ставок платежей и суммы КВ с исходным снимком.
Отчёт не исправляет неоднозначные исторические ссылки автоматически.

После этих миграций автоматический откат только образов на прежний код
несовместим с несколькими версиями ставок. При неудаче первого запуска
сохранить окно обслуживания и выпустить совместимое исправление; восстановление
прежнего состояния требует согласованного восстановления образов и БД из копии.
Просто откатывать миграции и удалять используемые ставки нельзя.

## Сервисы и runtime

| Сервис | Образ / процесс | Проверка |
|---|---|---|
| `db` | `postgres:15-alpine` | `pg_isready` |
| `redis` | `redis:7-alpine`, AOF | `redis-cli ping` |
| `web` | `insurance_broker_web:latest`, Gunicorn, 3 workers, timeout 120 | `python -m apps.core.health` |
| `celery_worker` | `insurance_broker_celery_worker:latest` | `celery -A config inspect ping` |
| `celery_beat` | `insurance_broker_celery_beat:latest`, DatabaseScheduler | Состояние running |
| `nginx` | `nginx:alpine` | Локальный `/health/` Nginx |
| `certbot` | `certbot/certbot`, renewal loop | Состояние running |

Три app-тега указывают на один загруженный CI-образ. App build-блоков в Compose
нет. Обязательный root-owned override задаёт UID/GID `10001:10001`, пустой
entrypoint, `cap_drop: [ALL]` и `no-new-privileges:true`. Base Compose отдельно
не отражает эффективную политику: в нём остаётся `gosu app` entrypoint.
Миграции и static выполняются контроллером один раз, до переключения приложений.

Проект Compose — **`insurance_broker`**. Только Nginx публикует 80/443;
`backend` соединяет БД/Redis с приложениями, `frontend` — web/Nginx/certbot.
Все сервисы имеют `restart: unless-stopped`, docker json-логи — 10 МБ × 3 файла.
Certbot запускает renewal каждые 12 часов, Nginx делает reload каждые 6 часов;
успех продления проверяется отдельно в [SSL-руководстве](DNS_SSL_SETUP.md).

## Тома и каталоги

| Имя в Compose | Фактический volume | Содержимое |
|---|---|---|
| `postgres_data` | `insurance_broker_postgres_data` | PostgreSQL |
| `redis_data` | `insurance_broker_redis_data` | Redis AOF |
| `static_volume` | `insurance_broker_static_volume` | Static, web → Nginx read-only |
| `media_volume` | `insurance_broker_media_volume` | Загрузки; Nginx read-only |

Bind mounts: `logs/`, `logs/nginx/`, `nginx/*.conf`, `certbot/conf/`,
`certbot/www/`. Web читает `/root/insurance_broker_backups` как
`/app/server_backups:ro`. Удаление named volumes удаляет данные.
`POSTGRES_*` из `.env.prod` маппируются в `DB_*` приложений;
[параметры и приоритет](ENVIRONMENT_VARIABLES.md).

## Что обновляет релиз

| Обычный релиз | Отдельная административная установка |
|---|---|
| Код и зависимости app-образа | Compose и security override |
| Миграции и собранная static | `.env.prod`, gate/controller, SSH и sudoers |
| Три app-контейнера и Nginx | Nginx-конфигурация, TLS/DNS, host-скрипты и cron |

`db`, `redis`, `certbot` и их образы обычной активацией не пересоздаются.
Хеши `docker-compose.prod.yml`, `scripts/deploy/security.override.yml`,
`nginx/nginx.conf`, `nginx/default.conf` сравниваются с сервером до upload.
При расхождении администратор проверяет и устанавливает изменения; повторный
запуск CI не обходит проверку. [Граница доступа](SECURITY.md).

## Пути и идентификаторы релиза

- URL: `https://polis.insflow.ru/`.
- Каталог хоста: `/root/insurance_broker`; после релиза это не актуальный
  Git checkout приложения.
- Состояние: `/var/lib/onlinepolis-deploy/releases/<run_id>-<run_attempt>/`.
- Снимки установщика: `/root/.local/state/onlinepolis-deploy/installer/`.
- Защищённые конфигурационные файлы: [SECURITY.md](SECURITY.md#защищённые-файлы).

CI image ref содержит commit SHA, run ID и attempt; `DEPLOYMENT_ID` —
`<run_id>-<run_attempt>`. Повтор только failed deploy job использует исходные
build outputs. После истечения artifact нужен полный workflow с новой сборкой
и проверками.

## Административный Compose

Контроллер использует Compose plugin с явными project directory/name, env file
и обоими защищёнными файлами. Та же команда для административной bash-сессии:

```bash
cd /root/insurance_broker
set +x
set -a
source .env.prod
set +a
prod_compose() {
  docker compose --compatibility \
    --project-directory /root/insurance_broker -p insurance_broker \
    --env-file /root/insurance_broker/.env.prod \
    -f /etc/onlinepolis-deploy/compose.yml \
    -f /etc/onlinepolis-deploy/security.override.yml "$@"
}
prod_compose config --quiet
prod_compose ps
```

Развёрнутый `config` и полный container env содержат секреты. Ключ CI
административного shell не предоставляет. Legacy Compose v1 не является
процедурой пересоздания production-контейнеров.

## Проверка релиза

Проверьте job `deploy` и, при его ошибке, `rollback` в Actions.
`status` проверяет конфигурацию, **не** здоровье приложения.
`health <deployment_id>` принимает идентификатор активированного verified
релиза, не произвольный SHA. Сравнивайте фактические image IDs и revision;
`git rev-parse HEAD` на хосте не подтверждает работающий код.
Команды диагностики — в [MONITORING.md](MONITORING.md).

## Восстановление релиза

До загрузки нового образа контроллер сохраняет image IDs и теги
`onlinepolis-rollback:<deployment_id>-<service>` прежних приложений.
При ошибке активации он пытается вернуть их; при падении deploy job workflow
дополнительно вызывает `rollback <deployment_id>`. Повтор уже выполненного
rollback идемпотентен. Контроллер отказывается менять посторонний, более новый
релиз. Прерванная активация требует оценки совместимости схемы перед повтором.

**Миграции/данные БД, media, собранная static и host-конфигурация автоматически
назад не возвращаются.** Если старый код несовместим с применённой схемой,
возврата образов недостаточно. Сохраните rollback-теги и состояние релиза
до принятого решения. `git reset`, server-side build, `scripts/deploy.sh`,
`down -v`, массовый prune и `import-database.sh` не входят в эту процедуру.
Восстановление данных — отдельная [инструкция](BACKUP_RESTORE.md).

## Первоначальное развёртывание

Workflow обновляет **подготовленный работающий стек**: перед первой активацией
контроллер сохраняет image IDs трёх существующих app-контейнеров. Установщик
SSH-доступа не устанавливает Docker, данные, DNS или сертификаты.

Администратор отдельно готовит:

1. Linux amd64, Docker Engine, Compose plugin, Python 3, SSH/sudo и утилиты,
   проверяемые `scripts/deploy/install.sh`.
2. Домен, HTTP/HTTPS и ACME по [DNS_SSL_SETUP.md](DNS_SSL_SETUP.md).
3. Проверенные Compose, Nginx и host-скрипты в `/root/insurance_broker`,
   `.env.prod` с корректными параметрами, root:root и `0600`.
4. Named volumes, logs/certbot и запись UID/GID `10001:10001` в рабочие
   каталоги приложения.
5. Проверенный образ, данные либо проверенный комплект БД/media, миграции
   и static. Для переезда — [план восстановления](BACKUP_RESTORE.md).
6. Работающие семь сервисов, включая существующие web/worker/beat перед
   первым managed release.

При начальном запуске применяется security override. Он убирает entrypoint,
поэтому права, миграции и static готовятся отдельно от запуска контейнеров.
Единого проверенного cold-start-скрипта в репозитории нет; старое
`docker-compose up --build` действующую схему не воспроизводит.

Затем устанавливается [ограниченный SSH-вход](SECURITY.md#установка-ограниченного-доступа),
проверяются `status`, protected hashes, полный релиз и `health`.
Backup/cron, logrotate, Telegram-туннель и SMTP-доступность проверяются отдельно.
Для смены секретов используется самостоятельная
[инструкция по ротации](SECRETS_ROTATION.md).
