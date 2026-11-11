# Мониторинг и логи

Сверено с [Compose](../docker-compose.prod.yml),
[health module](../apps/core/health.py),
[system_health_check](../apps/core/management/commands/system_health_check.py),
[settings](../config/settings.py) и
[контроллером](../scripts/deploy/controller.py) 2026-11-11.
Команды ниже выполняет администратор; ключ CI не предоставляет произвольный shell.

## Три уровня проверки

| Проверка | Что подтверждает |
|---|---|
| Nginx `/health/` | Ответ самого Nginx; Django не вызывается |
| `python -m apps.core.health` в web | Прямой ответ Gunicorn/Django, без обходного «зелёного» proxy health |
| Controller `health <deployment_id>` | Verified release, image IDs трёх app-контейнеров, runtime policy, все семь сервисов, HTTPS login |

`status` контроллера проверяет протокол и защищённую конфигурацию. Это не
замена `health`. Зелёный локальный pytest не подтверждает состояние production.

## Основные команды

```bash
docker ps --format 'table {{.Names}}	{{.Status}}'
docker exec insurance_broker_web python -m apps.core.health
docker exec insurance_broker_web python manage.py system_health_check --check-all
docker stats --no-stream
df -h
```

`system_health_check --check-all` проверяет БД, диск/память, web, настроенный
Telegram proxy и свежесть бэкапов. Web-проверку нужно выполнять именно
в web-контейнере. `--notify-telegram --notify-vk` включает реальные уведомления;
по умолчанию они зависят от смены состояния, `--notify-always` не отменяет
дедупликацию и лимиты доставки. Для обычной диагностики эти флаги не нужны.

Проверка бэкапов читает `last_status.json`, а не просто наличие последнего
архива: учитываются result и возраст записи. Пути выбираются из
`BACKUP_DB_DIR`/`BACKUP_MEDIA_DIR`, затем `BACKUP_BASE_DIR`, затем
`/app/server_backups`, затем домашнего каталога. Web получает серверные копии
через read-only bind mount. [Контракт и восстановление](BACKUP_RESTORE.md).

## Логи

```bash
docker logs --tail=100 insurance_broker_web
docker logs --tail=100 insurance_broker_celery_worker
docker logs --tail=100 insurance_broker_nginx
docker logs --tail=100 insurance_broker_certbot
```

На хосте `/root/insurance_broker/logs/`:

- `django.log` и `security.log` — приложение и события безопасности;
- `nginx/access.log`, `nginx/error.log` — persistent Nginx-логи;
- `backup-db.log`, `backup-media.log`, `backup-cleanup.log` — логи расписания,
  если cron установлен по соответствующему скрипту.

Docker json-логи ротируются: 10 МБ × 3 файла. Django использует file handlers;
для persistent Nginx-логов есть [setup-logrotate.sh](../scripts/setup-logrotate.sh).
Проверяйте реально установленную политику хоста отдельно.

`SensitiveDataFilter` маскирует секреты в Django handlers. Начальный переход
из InsFlow содержит одноразовый код: Nginx специально убирает query и referer
этого маршрута из access log. Не заменяйте формат логов без сохранения маскирования.

## Проверка работающего кода

```bash
docker inspect --format '{{.Image}} {{.Config.User}}' insurance_broker_web
docker exec insurance_broker_web python -m django --version
```

Сравнивайте загруженный image ID с результатом controller, а revision —
с OCI label проверенного образа. Три app-контейнера должны работать на одном
загруженном образе. Каталог `/root/insurance_broker` не обновляется checkout
при каждом релизе, поэтому `git rev-parse HEAD` на хосте этого не доказывает.

Полный `docker inspect` содержит окружение; не публикуйте его. Для Compose
используйте защищённую команду из
[руководства по деплою](DEPLOYMENT.md).

## Уведомления и внешние инструменты

[Telegram/VK](NOTIFICATIONS_PIPELINE.md) получают ошибки, дайджест и
служебные сообщения. Успех постановки Celery-задачи не доказывает доставки.
Повторный bash-разбор логов не является вторым обязательным каналом.

`scripts/monitor-health.sh` — отдельная старая
Compose/mail-утилита, а не реализация controller health и не доказательство
наличия внешнего uptime-мониторинга. Расписания cron и внешние сервисы
подтверждаются на сервере, не по наличию скрипта в репозитории.


## Sentry

Источник — [config/settings.py](../config/settings.py); это описание SDK,
а не новая проверка приёма событий в production.

Непустой `SENTRY_DSN` включает Django/Celery/Redis integrations. В тестах DSN
принудительно пустой. `SENTRY_RELEASE` задаёт метку релиза; CI её автоматически
не устанавливает. Defaults — в [справочнике окружения](ENVIRONMENT_VARIABLES.md#параметры-которые-читает-python).
Изменённое окружение применяется через recreate по
[инструкции ротации](SECRETS_ROTATION.md).

SDK использует production/development по DEBUG, `sample_rate=1.0`,
`traces_sample_rate=0.1` в production и `0.0` при DEBUG,
`send_default_pii=False`, `attach_stacktrace=True`, `max_breadcrumbs=50`.
Project alerts в интерфейсе Sentry репозиторием не управляются.

В SDK напрямую передаётся `_sentry_before_send`, определённый до инициализации.
Он следует [контракту Sentry](https://docs.sentry.io/platforms/python/configuration/filtering/#using-before-send):
возвращает исходное событие для отправки или `None` для отбрасывания.

- Отбрасывает `DisallowedHost`, `SuspiciousOperation`, `PermissionDenied`
  и исключения с сообщениями `broken pipe`, `connection reset by peer`,
  `client disconnected` без учёта регистра.
- Сохраняет остальные ошибки, включая реальный отказ соединения,
  а также сообщения без exception и с пустым `exc_info`.
- Не изменяет содержимое сохраняемого события.

Ранее условие было инвертировано (B-15). Исправление проверяется в
[test_sentry_filter.py](../config/tests/test_sentry_filter.py): тесты получают
callback из фактических параметров инициализации и проверяют как его результат,
так и envelopes настоящего SDK 2.19.2 через transport в памяти. Сетевые
соединения в этих тестах запрещены; тестовые события получателям не отправляются.

Состояние выкладки и оставшаяся production-проверка — в
[BACKLOG.md](BACKLOG.md). После выкладки отдельно проверяются эффективные DSN/release
и получение согласованного тестового события в нужном проекте Sentry.
Наличие DSN не подтверждает доставку или настройку alerts.
